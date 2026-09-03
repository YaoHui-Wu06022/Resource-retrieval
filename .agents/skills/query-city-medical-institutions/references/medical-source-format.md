# 医疗机构来源清单格式

`government_source.json` 是医疗 Skill 的来源证据文件，**每个行政单位一份**，
放在该行政单位自己的目录下；Agent 检索后写回，固定脚本只解析其中
`status = ready` 的来源，并校验顶层 `city_context` 与
`administrative_unit`。

## 顶层

| 字段 | 说明 |
| --- | --- |
| `stage` | 固定为 `medical_institutions_government_source` |
| `city_context` | 完整城市上下文，原样复制 `city_context.json` 内容 |
| `administrative_unit` | 本文件对应的直接下级行政单位，必须原样取自 `city_context.subdivisions` 中的一项 |
| `sources` | 来源数组 |

同一城市运行中，每个直接下级行政单位一个目录、一份清单；来源检索默认按
该行政单位进行，跨区来源（如市级名录页按行标明行政区）可复用时，只保留
属于本行政单位的行。

## 来源项

| 字段 | 说明 |
| --- | --- |
| `source_id` | 来源唯一 ID |
| `authority` | 发证/主管部门名称 |
| `source_type` | `xlsx_attachment` / `embedded_html_list` / `html_card_list` / `html_table_page` / `query_page` 等文件形态 |
| `url` | 原始页面地址 |
| `local_file` | 相对本行政单位目录的下载文件，未下载时为空 |
| `snapshot_date` | 官方“数据截至”日期 |
| `category_coverage` | 该来源覆盖的机构类别 |
| `status` | `ready` / `missing` / `no_official_source` |
| `priority` | 跨来源合并优先级，数字越小越优先 |

网页内嵌列表类来源可用 `record_kind` 标识栏目形态（如发证机构、
社区健康服务中心），用于规则修饰选择字段映射。

## 检查与提取

- `inspect`：`government_source.json` → `extraction_plan.json`
  （stage = `medical_institutions_extraction_plan`，Agent 复核规则后把
  来源设为 `review_status = ready`、规则设 `approved = true`）。
- `extract`：已复核 `extraction_plan.json` → `address_records.json`；
  提取后按登记号或机构名+地址跨来源去重，空地址记录保留在结果中。

提取按行政单位目录串行执行；来源行若标明不属于当前 `administrative_unit`，
由提取阶段剔除并计入 `skipped_out_of_scope_count`。

## 地址记录属性

公共地址记录 `attributes` 固定包含：

- `administrative_unit`：本行政单位目标区（`subdivision_scope=subdivision`
  时作为地址规范化目标区，也用于 Excel 分单位校验）
- `subdivision_scope`：固定 `subdivision`（按直接下级行政单位检索）
- `institution_type`（官方原文，缺失为空）
- `institution_level`（官方原文，如 `三级甲等`/`无级别`，缺失为空）
- `license_no`（有则填，无则空）
- `license_administrative_unit`：来源标注的执照登记区，缺失时用
  `administrative_unit`
- `source_id` / `source_authority` / `snapshot_date` / `source_row`

## 工作簿异常行

`build_excel.py` 从各行政单位目录读取 `processed_address_records.json`，
生成每区一份工作簿和一份城市总表，不再接收异常清单文件；异常机构行为
最终地址为空且无可用官方原文（或带 `abnormal_reason`）的记录。
