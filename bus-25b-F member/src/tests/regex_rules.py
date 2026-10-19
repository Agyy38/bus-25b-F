"""F 的共用正則規則；格式符合不代表語義正確。"""
import re
from datetime import datetime

STATION = re.compile(r"[MT]\d+(?:/\d+)?")
PLATE = re.compile(r"[A-Z]{2}\d{4}")
SPEED = re.compile(r"\d{1,3}")
STOP = re.compile(r"\s*(?P<code>[MTC]\d+(?:/\d+)?)\s+(?P<name>\S(?:.*\S)?)\s*")
PERIOD = re.compile(
    r"(?P<start_date>\d{4}年\d{1,2}月\d{1,2}日)\s*"
    r"(?P<start_time>\d{1,2}:\d{2})?\s*(?:開始|开始)\s*至\s*"
    r"(?P<end_date>\d{4}年\d{1,2}月\d{1,2}日)\s*"
    r"(?P<end_time>\d{1,2}:\d{2}|尾班車|尾班车)?")
DOM_STOP = re.compile(r"(?<!\w)([MTC]\d+(?:/\d+)?)-")
DOM_BUS = re.compile(r"(?<!\w)([A-Z]{2}\d{4})(?!\w)(?:\s+(\d{1,3})\s*km/h)?")


def parse_stop(text):
    match = STOP.fullmatch(text)
    if not match:
        raise ValueError("無法解析站碼與站名")
    return match.groupdict()


def parse_period(text):
    match = PERIOD.fullmatch(re.sub(r"<br\s*/?>", " ", text, flags=re.I).strip())
    if not match:
        raise ValueError("無法解析改道時段")
    result = match.groupdict()
    for side in ("start", "end"):
        datetime.strptime(result[side + "_date"], "%Y年%m月%d日")
        value = result[side + "_time"]
        if value and not value.startswith("尾班"):
            datetime.strptime(value, "%H:%M")
    return result


def parse_dom(text):
    """輸入可見文字；先切站點邊界，再解析每站多輛車。"""
    markers = list(DOM_STOP.finditer(text))
    result = []
    for i, mark in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        block = text[mark.end():end].strip()
        buses = list(DOM_BUS.finditer(block))
        name = block[:buses[0].start()].strip() if buses else block
        result.append({"code": mark[1], "name": name,
                       "buses": [{"plate": b[1], "speed": b[2]} for b in buses]})
    return result
