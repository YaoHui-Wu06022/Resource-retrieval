# 医疗机构来源清单格式

`government_source.json` 是医疗 Skill 的来源证据文件，Agent 检索后写回，
固定脚本只解析其中 `status = ready` 的来源。

## 顶层

| 字段 | 说明 |
| --- | --- |
| `stage` | 固定为 `medical_institutions_government_source` |
| `city` | 标准城市名 |
| `sources` | 来源数组 |

## 来源项

| 字段 | 说明 |
| --- | --- |
| `source_id` | 来源唯一 ID |
| `city` | 城市名 |
| `authority` | 发证/主管部门名称 |
| `source_type` | `xlsx_attachment` / `embedded_html_list` / `html_card_list` / `query_page` 等文件形态 |
| `url` | 原始页面地址 |
| `local_file` | 相对运行目录的下载文件，未下载时为空 |
| `snapshot_date` | 官方“数据截至”日期 |
| `category_coverage` | 该来源覆盖的机构类别 |
| `status` | `ready` / `missing` / `no_official_source` |
| `priority` | 跨来源合并优先级，数字越小越优先 |

网页内嵌列表类来源可用 `record_kind` 标识栏目形态（如发证机构、
社区健康服务中心），用于解析器选择字段映射。

## 地址记录属性

公共地址记录 `attributes` 固定包含：

- `administrative_unit`
- `institution_type`（官方原文，缺失为空）
- `institution_level`（官方原文，如 `三级甲等`/`无级别`，缺失为空）
- `license_no`（有则填，无则空）
- `source_id` / `source_authority` / `snapshot_date` / `source_row`
