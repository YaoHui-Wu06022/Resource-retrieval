# scripts 处理脚本

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `medical_government_flow.py` | 政府资料流程 CLI：`list-links` / `download` / `collect-details` / `inspect` / `extract`；词表、来源清单适配、引擎调用与跨来源去重。 |
| `medical_common.py` | 医疗记录构造、执业地址拆分、外市剔除与跨来源去重。 |
| `build_excel.py` | 收集各行政单位 processed 结果并生成区级工作簿与城市总表；区级工作簿含「机构信息」「异常机构」，总表为“机构信息”汇总 + 各区工作表且不含异常机构表；机构级别为“未定级/无定级/无级别”时输出为空。 |

## 修改记录

### 2026-09-03

- 删除旧 `medical_source_parsers.py` 与 `build_medical_address_records.py`，
  统一走 `medical_government_flow.py` 的 inspect/extract 公共链路；
  废除 `anomaly_records.json`，异常行改由 `build_excel.py` 推导；
  `extract` 重新接入 `deduplicate_records`，修复多地址段
  `source_reference` 累积问题。
- 医疗流程改为按直接下级行政单位默认分区检索：每区目录一份
  `government_source.json`（顶层 `city_context` + `administrative_unit`）；
  地址记录 attributes 使用 `subdivision_scope=subdivision` 与
  `license_administrative_unit`，多址拆分的无区名段以目标区补区；
  `build_excel.py` 改为 `--input-dir` 汇总各行政单位 processed 结果，
  生成每区工作簿与城市总表。
- 城市总表改为与基础教育一致的结构：先输出“机构信息”汇总表，再按行政
  单位各出一张工作表；异常机构表只保留在每区工作簿，总表不再写入
  异常机构表。
- 工作簿输出规则：机构级别为“未定级/无定级/无级别”的单元格显示为空，
  原始 processed 记录中的官方原文保持不变。
