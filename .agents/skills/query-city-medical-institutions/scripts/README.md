# scripts 处理脚本

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `medical_common.py` | 医疗机构记录共用的拆分、外市判定、去重与 payload 构造。 |
| `medical_government_flow.py` | 调用公共 `inspect_government_source`/`extract_government_records`。 |
| `build_excel.py` | 生成“机构信息/异常机构”城市总表与区级工作簿。 |

## 修改记录

### 2026-09-03

- 删除旧 `medical_source_parsers.py` 与 `build_medical_address_records.py`，
  统一走 `medical_government_flow.py` 的 inspect/extract 公共链路。

### 2026-09-02

- 新增全部脚本与来源解析器；
- 运行测试：`pytest scripts/tests -q` 7 passed。
