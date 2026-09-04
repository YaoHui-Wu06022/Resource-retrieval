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
属于本行政单位的行；最终 Excel 阶段再按物理地址做城市级去重与分桶，
“登记区”字段只作来源属性，不用于剔除跨区执业地点。

## 来源项

| 字段 | 说明 |
| --- | --- |
| `source_id` | 来源唯一 ID |
| `authority` | 发证/主管部门名称 |
| `source_type` | `xlsx_attachment` / `embedded_html_list` / `html_card_list` / `html_table_page` / `query_page` / `query_platform` 等文件形态 |
| `url` | 原始页面地址 |
| `local_file` | 相对本行政单位目录的下载文件，未下载时为空 |
| `snapshot_date` | 官方“数据截至”日期 |
| `category_coverage` | 该来源覆盖的机构类别 |
| `status` | `pending` / `ready` / `missing` / `no_official_source`；`query_platform` 抓取成功前为 `pending`，抓取后回写 `ready` 与 `local_file` |
| `priority` | 跨来源合并优先级，数字越小越优先 |

网页内嵌列表类来源可用 `record_kind` 标识栏目形态（如发证机构、
社区健康服务中心），用于规则修饰选择字段映射。

`query_platform` 来源除上表字段外还须携带 `platform` 配置与抓取结果：

- `platform.endpoint` / `allowed_domain` / `callback`：平台分页接口、允许
  域名与 JSONP 回调名；`platform-query` 只请求允许域名内的地址。
- `platform.fixed_params`：每次请求固定的官方参数（如栏目
  `category_id`）。
- `platform.paging`：`page_param` / `page_size_param` / `page_size`
  （上限 500）/ `total_field` / `list_field`。
- `platform.district_filter`：按行政区过滤参数（`param`、`key`、可选
  `value`；`value` 缺省取清单顶层 `administrative_unit.name`，JSON 编码为
  `{"key": ["<区名>"]}`）。
- `platform.json_ext_field`：记录中 JSON 字符串字段名，抓取时展开为字段。
- `platform_result`（抓取后回写）：`count`、`record_count`、`page_count`、
  `raw_files`（原始 JSONP 页证据）、`pages`（逐页 URL/状态审计）与
  `fetched_at`；`snapshot_date` 记录平台“数据截至”日期。

抓取产物位于 `<行政单位目录>/sources/`：`<source_id>_page_<NN>.jsonp`
为原始响应证据，`<source_id>_records.json` 为展开 `json_ext` 的确定性
汇总（保留 `_page/_row`），`government_source.json` 的 `local_file` 指向
汇总文件。

`no_official_source` 条目须用 `category_coverage` 声明缺全量来源的类别，
类别名使用质量闸门的大类：医院、基层医疗卫生机构、门诊部与诊所、
医学检验机构、其他。

## 检查与提取

- `inspect`：`government_source.json` → `extraction_plan.json`
  （stage = `medical_institutions_extraction_plan`，Agent 复核规则后把
  来源设为 `review_status = ready`、规则设 `approved = true`）。
- `extract`：已复核 `extraction_plan.json` → `address_records.json`；
  提取后按登记号或机构名+地址跨来源去重，空地址记录保留在结果中。

提取按行政单位目录串行执行；来源行若标明不属于当前 `administrative_unit`，
由提取阶段剔除并计入 `skipped_out_of_scope_count`。

`query_platform` 汇总记录按 `yymc/yydz/szq/yytype/jb` 映射为机构名、
执业地址、所在行政区、机构类型与级别；平台 `yyid` 不作为登记号参与
去重，避免与区级表登记号格式不一致造成误合并。

## 质量闸门

`medical_quality_check.py` 在生成工作簿后、交付前执行，汇总各行政单位
processed 结果（与 `build_excel.py` 共用去重与分桶逻辑）后写出
`quality_report.json`：

- 有 ready `query_platform` 来源的区，主表行数低于平台当区总数 × 90%
  （默认）判定未通过。
- 平台当区某大类达到阈值（默认 10 条）而交付为零，且清单没有对应
  `no_official_source` 理由时判定未通过。
- 没有任何 ready 全量来源的区判定未通过。
- 报告记录每区平台数、交付行数、比例、平台大类计数、交付大类计数与
  未通过原因；命令退出码非 0 时禁止交付。

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
