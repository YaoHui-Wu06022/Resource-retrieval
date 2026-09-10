# 医疗机构来源清单格式

`government_source.json`：每行政单位一份、放在该单位目录；Agent 写回，固定脚本只解析 `status=ready` 来源，并校验顶层 `city_context`/`administrative_unit`。

## 顶层

| 字段 | 说明 |
| --- | --- |
| `stage` | 固定 `medical_institutions_government_source` |
| `city_context` | `city_context.json` 内容原样 |
| `administrative_unit` | 必须是 `city_context.subdivisions` 中一项 |
| `sources` | 来源数组 |

同一城市每区一目录一清单；跨区来源只保留本区行；“登记区”仅作来源属性，不剔除跨区执业地点（最终 Excel 按物理地址去重分桶）。

## 来源项

| 字段 | 说明 |
| --- | --- |
| `source_id` | 唯一 ID |
| `authority` | 发证/主管部门 |
| `source_type` | `xlsx_attachment`/`embedded_html_list`/`html_card_list`/`html_table_page`/`query_page`/`query_platform` 等 |
| `url` | 原始页面 |
| `local_file` | 相对本区目录文件；未下载为空 |
| `snapshot_date` | 官方“数据截至”日期 |
| `category_coverage` | 覆盖类别 |
| `status` | `pending`/`ready`/`missing`/`no_official_source`；`query_platform` 成功前 `pending`，后回写 `ready`+`local_file` |
| `priority` | 跨来源合并优先级，越小越优先 |

网页内嵌列表可加 `record_kind`（如发证机构、社康中心）供规则修饰选字段映射。

`query_platform` 另须携带：

- `platform.endpoint/allowed_domain/callback`：分页接口、允许域名、JSONP 回调名；只请求允许域内地址。
- `platform.fixed_params`：固定官方参数（如 `category_id`）。
- `platform.paging`：`page_param`/`page_size_param`/`page_size`(≤500)/`total_field`/`list_field`。
- `platform.district_filter`：`param`/`key`/可选 `value`（缺省取区名，JSON 编码 `{"key":["<区名>"]}`）。
- `platform.json_ext_field`：记录中 JSON 字符串字段名，抓取时展开。
- `platform_result`（回写）：`count`/`record_count`/`page_count`/`raw_files`/`pages`/`fetched_at`；`snapshot_date` 记平台数据截至。

抓取产物在 `<单位目录>/sources/`：`<source_id>_page_<NN>.jsonp`（原始证据）、`<source_id>_records.json`（展开 json_ext 的确定性汇总，保留 `_page/_row`）；`local_file` 指向汇总文件。

`no_official_source` 须用 `category_coverage` 声明缺全量来源的类别，类别名用质量闸门大类：医院、基层医疗卫生机构、门诊部与诊所、医学检验机构、其他。

## 检查与提取

- `inspect`：`government_source.json` → `extraction_plan.json`（stage=`medical_institutions_extraction_plan`；规则 `approved=true`、来源 `review_status=ready`）。
- `extract`：已复核计划 → `address_records.json`；按登记号或机构名+地址跨来源去重，空地址记录保留。
- 按区串行执行；来源行不属于当前单位时剔除并计 `skipped_out_of_scope_count`。
- `query_platform` 汇总记录按 `yymc/yydz/szq/yytype/jb` 映射机构名/执业地址/所在行政区/类型/级别；`yyid` 不作为登记号参与去重（避免与区级登记号格式不一致误合并）。

## 质量闸门

`medical_quality_check.py` 在生成工作簿后、交付前执行，输出 `quality_report.json`：

- 有 ready `query_platform` 的区：主表行数 < 平台当区总数 × 90%（默认）→ 未通过。
- 平台某大类达阈值（默认 10）而交付为零且无对应 `no_official_source` → 未通过。
- 无任何 ready 全量来源的区 → 未通过。
- 报告含每区平台数、交付行数、比例、平台/交付大类计数与未通过原因；退出码非 0 禁止交付。

## 地址记录属性

`attributes` 固定含：

- `administrative_unit`（目标区，`subdivision_scope=subdivision` 时作规范化目标与分单位校验）
- `subdivision_scope`（固定 `subdivision`）
- `institution_type`/`institution_level`（官方原文，缺失空）
- `license_no`（有则填）
- `license_administrative_unit`（执照登记区，缺失用 `administrative_unit`）
- `source_id`/`source_authority`/`snapshot_date`/`source_row`

## 工作簿异常行

`build_excel.py` 从各区 processed 结果推导，不再接收异常清单文件：最终地址为空且无可用官方原文（或带 `abnormal_reason`）的记录进入该区异常机构表。
