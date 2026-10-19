# F 测试与合规：本地交付

已写入指定的 DS-group-project/bus-25b-arrival 项目：

- src/tests/validate.py：离线数据质量检查，按接口与方向查断档，识别重复、字段异常和API失败。
- src/tests/regex_rules.py：时间段、复合站名、字段格式、页面文字解析的参考实现。
- src/tests/test_validate.py、test_regex.py：25个测试方法，通过。
- docs/F-testing-guide.md：运行方法、规则及交接说明。
- docs/F-compliance.md：官方条款证据、8项审查内容与待补材料。
- docs/F-issue-log.md：11项问题和跟进状态。
- docs/F-test-results.txt：实际运行环境及验收证据。
- output/F-validation/：JSON、Markdown、HTML报告。

## 如何运行

在PowerShell中执行：

```powershell
cd C:\Users\86136\DS-group-project\bus-25b-arrival
python -B -m unittest discover -s src/tests -p "test_*.py" -v
python -B src/tests/validate.py src/samples/sample-2026-10-03.jsonl.gz
```

第二条命令遇到待核实项返回1，仍生成报告；样本的C700规则冲突属于此类，不是崩溃。

## 实际发现

499条快照，1557条车辆观测。四个动态流最大间隔12秒，没有>180秒缺口。空速度101条，载客等级无读数851条；路况两指标164次不一致。C700在样本出现249次，文档的[MT]站码规则未覆盖，已记录而未删除。

## 尚需材料

1. 《爬虫失控判刑.pdf》：仓库未提供，不能伪造案例摘要。
2. A的完整采集数据和实际起止：目前只验收22分钟样本。
3. BIS独立条款、robots结果与授权适用范围：主站条款已查阅，但不能自动套用。
4. 同时间页面文字与接口记录：用于T6真实交叉验证；B/C实现到位后补集成验收。

25个测试在本机Python3.13.15标准库环境通过，未宣称项目约定的Python3.11采集环境已验收。未修改原始数据或A代码，未提交和推送Git。

主站来源：[交通事务局使用条款](https://www.dsat.gov.mo/dsat/subpage.aspx?a_id=1614844508)，2026-10-19查阅。
