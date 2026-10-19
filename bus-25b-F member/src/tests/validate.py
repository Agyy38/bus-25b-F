"""離線驗證 JSONL/gzip，不修改資料、不連網、不啟動採集器。"""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import html
import json
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import parse_qs, urlsplit
from regex_rules import STATION, PLATE, SPEED

ROOT = Path(__file__).resolve().parents[2]
MACAU = timezone(timedelta(hours=8))
ENDPOINTS = {"/macauweb/routestation/bus": "bus",
             "/ddbus/common/supermap/routeStation/traffic": "traffic",
             "/macauweb/getRouteData.html": "stops"}


def validate(paths, gap_seconds=180):
    counts, fields, issues = Counter(), Counter(), Counter()
    examples, streams = {}, []

    def issue(code, where):
        issues[code] += 1
        examples.setdefault(code, [])
        if len(examples[code]) < 10:
            examples[code].append(where)

    # 磁碟暫存索引，避免把多日原始回應放進記憶體。
    with tempfile.TemporaryDirectory(prefix="bus-f-") as temp:
        db = sqlite3.connect(str(Path(temp) / "index.sqlite"))
        try:
            db.execute("CREATE TABLE records(kind, direction, t REAL, ref, digest UNIQUE, valid INTEGER)")
            for path in paths:
                opener = gzip.open if path.suffix == ".gz" else open
                try:
                    with opener(path, "rt", encoding="utf-8-sig") as source:
                        for number, line in enumerate(source, 1):
                            if not line.strip():
                                continue
                            counts["lines"] += 1
                            ref = f"{path.name}:{number}"
                            try:
                                rec = json.loads(line)
                            except ValueError:
                                issue("outer_json_invalid", ref); continue
                            if not isinstance(rec, dict) or any(k not in rec for k in ("recv_at", "url", "resp")):
                                issue("required_field_missing", ref); continue
                            if not isinstance(rec["url"], str) or not isinstance(rec["recv_at"], str):
                                issue("field_type_invalid", ref); continue
                            try:
                                dt = datetime.fromisoformat(rec["recv_at"])
                                dt = dt.replace(tzinfo=MACAU) if dt.tzinfo is None else dt.astimezone(MACAU)
                                url = urlsplit(rec["url"])
                            except ValueError:
                                issue("time_or_url_invalid", ref); continue
                            kind = ENDPOINTS.get(url.path)
                            if not kind:
                                issue("unknown_endpoint", ref); continue
                            params = parse_qs(url.query)
                            body = rec.get("reqBody")
                            if body is not None and not isinstance(body, str):
                                issue("request_body_invalid", ref); continue
                            for key, values in parse_qs(body or "").items():
                                params.setdefault(key, []).extend(values)
                            directions = set(params.get("dir", []) + params.get("direction", []))
                            if len(directions) != 1 or not directions <= {"0", "1"}:
                                issue("direction_unknown_or_conflicting", ref); continue
                            direction = directions.pop()
                            counts[f"{kind}/dir={direction}"] += 1
                            if not isinstance(rec["resp"], str):
                                issue("response_type_invalid", ref); continue
                            digest = hashlib.sha256(json.dumps(
                                [kind, direction, dt.isoformat(), rec["resp"]], ensure_ascii=False
                            ).encode()).hexdigest()
                            try:
                                db.execute("INSERT INTO records VALUES(?,?,?,?,?,0)",
                                           (kind, direction, dt.timestamp(), ref, digest))
                            except sqlite3.IntegrityError:
                                issue("duplicate_snapshot", ref); continue
                            try:
                                payload = json.loads(rec["resp"])
                            except ValueError:
                                issue("response_json_invalid", ref); continue
                            if not isinstance(payload, dict):
                                issue("response_schema_invalid", ref); continue
                            header = payload.get("header")
                            status = header.get("status") if isinstance(header, dict) else None
                            status = payload.get("status", header if isinstance(header, str) else status)
                            if status is not None and status != "000":
                                issue("api_status_failure", ref); continue
                            if kind == "traffic":
                                data = payload.get("data", payload)
                                items = data.get("stationInfo") if isinstance(data, dict) else None
                                if items is None:
                                    items = payload.get("stationInfo")
                            else:
                                data = payload.get("data")
                                items = data.get("routeInfo") if isinstance(data, dict) else None
                            if not isinstance(items, list):
                                issue("response_schema_invalid", ref); continue
                            db.execute("UPDATE records SET valid=1 WHERE digest=?", (digest,))
                            if not items:
                                issue("empty_station_list", ref)
                            seen, bus_count = {}, 0
                            for index, stop in enumerate(items):
                                where = f"{ref}/station[{index}]"
                                if not isinstance(stop, dict):
                                    issue("station_type_invalid", where); continue
                                code = stop.get("stationCode" if kind == "traffic" else "staCode")
                                if not isinstance(code, str) or not STATION.fullmatch(code):
                                    issue("station_format_review", where)
                                if kind == "traffic":
                                    for key in ("trafficLevel", "newRouteTraffic"):
                                        if str(stop.get(key)) not in {"-1", "1", "2", "3"}:
                                            issue("traffic_value_invalid", where + "/" + key)
                                        if str(stop.get(key)) == "-1":
                                            fields[key + "_no_reading"] += 1
                                    if str(stop.get("trafficLevel")) != str(stop.get("newRouteTraffic")):
                                        fields["traffic_indicators_differ"] += 1
                                    continue
                                if kind != "bus":
                                    continue
                                buses = stop.get("busInfo")
                                if not isinstance(buses, list):
                                    issue("bus_list_invalid", where); continue
                                for j, bus in enumerate(buses):
                                    loc = f"{where}/bus[{j}]"
                                    if not isinstance(bus, dict):
                                        issue("bus_type_invalid", loc); continue
                                    bus_count += 1
                                    plate = bus.get("busPlate")
                                    if not isinstance(plate, str) or not PLATE.fullmatch(plate):
                                        issue("plate_format_review", loc)
                                    else:
                                        if plate in seen:
                                            issue("duplicate_vehicle" if seen[plate] == code else "vehicle_station_conflict", loc)
                                        seen[plate] = code
                                    speed = bus.get("speed")
                                    if "speed" not in bus:
                                        issue("speed_missing", loc)
                                    elif speed == "":
                                        fields["speed_empty_ambiguous"] += 1
                                    elif isinstance(speed, str) and SPEED.fullmatch(speed):
                                        fields["speed_zero" if int(speed) == 0 else "speed_numeric"] += 1
                                        if int(speed) > 120:
                                            issue("speed_plausibility_review", loc)
                                    else:
                                        issue("speed_format_invalid", loc)
                                    flow = bus.get("passengerFlow")
                                    valid_flow = (type(flow) is int and flow in range(-1, 6)) or (
                                        isinstance(flow, str) and flow in {"-1", "0", "1", "2", "3", "4", "5"})
                                    if not valid_flow:
                                        issue("passenger_flow_invalid", loc)
                                    else:
                                        fields["passenger_flow_string" if isinstance(flow, str) else "passenger_flow_integer"] += 1
                                        if int(flow) == -1:
                                            fields["passenger_flow_no_reading"] += 1
                            if kind == "bus":
                                fields["vehicle_observations"] += bus_count
                                if items and not bus_count:
                                    fields["no_bus_snapshots"] += 1
                except (OSError, EOFError, UnicodeError) as exc:
                    issue("file_read_error", f"{path.name}: {type(exc).__name__}")
            for kind in ("bus", "traffic", "stops"):
                for direction in ("0", "1"):
                    query = ("SELECT t, ref FROM records WHERE kind=? AND direction=? AND valid=1 "
                             "GROUP BY t ORDER BY t")
                    first = previous = last = None
                    total, maximum, gaps = 0, 0, 0
                    for stamp, ref in db.execute(query, (kind, direction)):
                        first = stamp if first is None else first
                        if previous is not None:
                            delta = stamp - previous
                            maximum = max(maximum, delta)
                            if kind != "stops" and delta > gap_seconds:
                                gaps += 1
                                issue("sampling_gap", f"{kind}/dir={direction}: {datetime.fromtimestamp(previous, MACAU).isoformat()} → {datetime.fromtimestamp(stamp, MACAU).isoformat()} ({delta:g}s), {ref}")
                        previous = last = stamp
                        total += 1
                    if not total and kind == "bus":
                        issue("missing_bus_direction", f"dir={direction}")
                    if total:
                        streams.append({"kind": kind, "direction": direction, "unique_times": total,
                                        "start": datetime.fromtimestamp(first, MACAU).isoformat(),
                                        "end": datetime.fromtimestamp(last, MACAU).isoformat(),
                                        "max_interval_sec": maximum, "gaps": gaps})
            if not counts["lines"]:
                issue("empty_input", "沒有非空記錄")
        finally:
            db.close()
    return {"counts": dict(counts), "fields": dict(fields), "issues": dict(issues),
            "examples": examples, "streams": streams, "gap_seconds": gap_seconds}


def render(report):
    lines = ["# F 資料品質檢查報告", "", "僅檢查提供的檔案；不代表完整 14 天、實際到站真值或法律合規認證。",
             f"斷檔閾值：>{report['gap_seconds']} 秒；按接口和方向分組，時間為 UTC+08:00。", "",
             "## 記錄與欄位統計", "", "```json", json.dumps({k: report[k] for k in ('counts', 'fields')}, ensure_ascii=False, indent=2), "```", "",
             "## 有效結構快照的時間覆蓋", "", "|接口|方向|不同時刻數|開始|結束|最大間隔秒|缺口數|", "|---|---|---:|---|---|---:|---:|"]
    for s in report["streams"]:
        lines.append("|" + "|".join(str(s[k]) for k in ("kind", "direction", "unique_times", "start", "end", "max_interval_sec", "gaps")) + "|")
    lines += ["", "## 異常與需核實項", "", "每類保留前 10 個定位示例，計數不截斷；報告不複製車牌或請求參數。", ""]
    for key, count in report["issues"].items():
        lines += [f"### {key}: {count}"] + [f"- {item}" for item in report["examples"][key]]
    if not report["issues"]:
        lines.append("本次規則未發現異常；不等於資料完全無誤。")
    lines += ["", "## 解讀限制", "", "空速度有歧義；-1 表示無讀數。站碼/車牌模式為待驗證假設，不自動刪除不符值。",
              "同內容不同採樣時刻不算重複。缺口為有效結構快照時間差，不等於停機時長。",
              "未提供預期採集起止時間，無法判定首尾缺失或全程覆蓋率；不採用口徑不明的每小時 630–680 條閾值。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--gap-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "F-validation")
    args = parser.parse_args()
    if args.gap_seconds <= 0:
        parser.error("gap-seconds 必須大於零")
    paths = []
    for path in args.inputs:
        paths.extend(sorted(path.glob("*.jsonl*")) if path.is_dir() else [path])
    paths = list(dict.fromkeys(p.resolve() for p in paths))
    report = validate(paths, args.gap_seconds)
    report["inputs"] = [str(p) for p in paths]
    report["generated_at"] = datetime.now(MACAU).isoformat()
    args.output.mkdir(parents=True, exist_ok=True)
    markdown = render(report)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "report.md").write_text(markdown, encoding="utf-8")
    (args.output / "report.html").write_text('<!doctype html><meta charset="utf-8"><title>F validation</title><style>body{max-width:1100px;margin:30px auto;font:16px sans-serif}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><pre>' + html.escape(markdown) + '</pre>', encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "issues": report["issues"]}, ensure_ascii=False, indent=2))
    print("報告：", args.output)
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
