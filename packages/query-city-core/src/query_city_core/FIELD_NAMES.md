# 公共接口字段名

本文件登记 `query_city_core` 跨模块传递的公开字段。新增、改名或删除公开字段时，必须先更新本文件，再修改生产者、消费者和测试。

## 城市上下文

由 `city.py` 生成，供地址处理及各类城市查询 skill 使用。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `stage` | string | 固定为 `city_context`。 |
| `input_city` | string | 去除首尾空白后的用户原始输入。 |
| `city_name` | string | 由城市目录标准化后的地级单位或直辖市名称。 |
| `province_name` | string \| null | 非直辖市的上级省级单位；直辖市为 `null`。 |
| `subdivisions` | array | 高德返回并整理后的直接下级行政单位列表。 |

## 直接下级行政单位

`subdivisions` 中的每一项使用以下字段。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `name` | string | 下级行政单位名称。 |
| `adcode` | string | 高德行政区划编码。 |
| `level` | string | 高德返回的行政层级，例如 `district`、`county` 或 `city`。 |

## 公共地址记录

`address_records`、`normalized_address_records` 和 `processed_address_records` 顶层均使用下列城市字段。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `city_context` | object | 完整保留城市上下文，不另设顶层 `city` 字段。其字段与“城市上下文”章节一致。 |

地址记录生产者必须把最初取得的 `city_context` 原样写入；后续地址处理阶段只读取并继续传递该对象。

### 地址解析输入

地址规范化完成后，每个 `items` 元素在进入 `address.verify.resolve_map_address()` 前使用下列字段。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `place_name` | string | 用于 POI 查询和名称比对的学校、校区或其他地点名称。 |
| `original_address` | string | 来源页面或资料中的原始地址文本；允许为空字符串。 |
| `normalized_address` | string | 基于 `city_context` 规范化后的地址；没有可用地址时为空字符串。 |
| `normalization_status` | string | `complete`、`partial`、`empty`、`invalid` 或 `conflict`。 |
| `source_nature` | string | `web_search` 表示学校官网页面信息；`government_information` 表示政府公开资料。 |
| `source_reference` | string | 实际取得该地址或地点线索的来源定位。 |
| `attributes` | object | 场景业务字段；如存在 `administrative_unit`，POI 结果必须与其区县一致。 |

### 地址解析输出

`processed_address_records.items` 在保留全部输入字段的基础上，固定增加下列字段。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `map_address` | string | 高德返回并按 `city_context` 规范化后的地址；未取得时为空字符串。 |
| `map_status` | string | `skipped`、`consistent`、`partial`、`conflict`、`poi_match`、`not_found`、`ambiguous` 或 `error`。 |
| `map_reason` | string | 地图查询、候选比较或跳过原因。 |
| `map_poi_type` | string | POI 查询命中时的高德 `type`；地理编码或未命中时为空字符串。 |
| `map_poi_typecode` | string | POI 查询命中时的高德 `typecode`；地理编码或未命中时为空字符串。 |
| `final_address` | string | 最终采用的规范地址；无法确认时为空字符串。 |
| `final_address_source` | string | `official` 表示来源地址，`map` 表示高德地址；无最终地址时为空字符串。 |
| `final_address_reason` | string | 说明最终选择来源地址、地图更详细地址或 POI 名称匹配地址的原因。 |

### 地址解析规则

| 来源与地址状态 | 高德查询 | 最终地址 |
| --- | --- | --- |
| `government_information` 且有道路或门牌等实际地址 | 不调用 | 直接采用政府资料地址。 |
| `government_information` 且只有学校/校区名称、区县或空地址 | POI | 仅唯一名称匹配、城市和区县条件均满足时采用地图地址。 |
| `web_search` 且有完整的道路或门牌地址 | 地理编码 | 市、区县、道路、门牌等双方均有的组件出现冲突时保留官网地址；无冲突时采用道路、门牌和位置文本更详细的一方。 |
| `web_search` 且只有学校/校区名称、区县或空地址 | POI | 仅唯一名称匹配、城市和区县条件均满足时采用地图地址。 |
| `web_search` 且道路地址不完整、无效或跨城市冲突 | 不调用 | 不生成最终地址。 |

### 公共地址处理职责与边界

公共入口为 `query_city_core.address.process.resolve_address_payload()`。它负责把每条来源地址处理成字段稳定、可供业务层继续使用的地图与最终地址结果。

| 阶段 | 公共层职责 |
| --- | --- |
| 输入校验 | 校验 `city_context`、`place_name`、`source_nature`、`source_reference` 和 `attributes`，保留业务层写入的其他字段。 |
| 来源地址规范化 | 清理地址标签、联系方式、邮编和空白，统一常见标点；依据 `city_context` 补齐可确定的城市及区县前缀；识别空地址、不完整地址、有效地址和跨城市冲突。 |
| 地图查询选择 | 根据 `source_nature`、`normalization_status` 及是否含道路或门牌，决定跳过地图、调用地理编码或按 `place_name` 调用 POI。 |
| 地图候选处理 | 将高德地址规范为与来源地址相同的城市前缀。地理编码候选逐条比较行政区、道路、门牌和地点锚点并选取状态最可靠的一条；POI 候选必须同时满足地点名称、城市、可选区县和类型条件。 |
| 单次 POI 候选去重 | 同一次 POI 查询中，合格候选按去除常见空白和标点后的规范地图地址合并；只有一个不同地址时才采用，多个不同地址标记为 `ambiguous`。这不是不同输入记录之间的去重。 |
| 最终地址选择 | 按来源性质、地址组件冲突和详细程度生成 `final_address`、`final_address_source` 与 `final_address_reason`；无法确认时保留空字符串。 |
| 结果输出 | 每条输入记录对应一条输出记录，保持原有顺序，并统计地图请求数、规范化状态、地图状态及非空最终地址数量。 |

公共层不执行以下业务处理：

- 不比较或合并 `items` 中的不同记录，即使它们具有相同的 `map_address` 或 `final_address`。
- 不根据学校、校区或其他业务身份决定同址记录应保留哪一条。
- 不删除 `final_address` 为空的记录；空地址及其失败状态继续保留在 `processed_address_records.json` 中。
- 不负责最终工作簿的字段选择、排序、连续编号或空地址过滤。

跨记录同址去重和最终输出筛选由各业务层在公共处理完成后负责。例如，高校业务使用 `build_university_address_post.py` 比较同校地图地址，再由 `build_excel.py` 过滤空地址并排序写入工作簿。

## 高校：城市名单筛选

由 `query-city-universities/scripts/filter_universities.py` 执行，是城市上下文进入高校 skill 的首个阶段。

| 字段名或载体 | 来源 | 使用方式 |
| --- | --- | --- |
| `city_name` | 城市上下文 | 唯一筛选条件。 |
| `学校名称`、`学校标识码`、`主管部门`、`所在地`、`办学层次`、`备注` | `全国普通高等学校名单.xlsx` | 仅保留 `所在地` 与 `city_name` 完全一致的行。 |
| `院校标签` | `985_universities.xlsx`、`211_universities.xlsx` | 仅本科院校可标记；学校同时命中时写 `985`，否则命中 211 时写 `211`，其余留空。 |
| `办学性质` | 教育部名单的 `备注` | 包含“中外合作办学”或“内地与港澳合作办学”写“中外合作”；包含“境外高等教育机构”写“境外机构”；包含“民办”写“民办”；备注为空写“公办”；其余写“待核验”。 |
| `city_universities.xlsx` | 筛选输出 | 位于 `output/<city_name>/<YYYY-MM-DD>/Higher_Education/`；固定列顺序：`学校名称`、`学校标识码`、`主管部门`、`所在地`、`办学层次`、`院校标签`、`办学性质`。 |
| `city_universities.json` | 筛选输出 | 与 Excel 位于同一目录，`stage` 固定为 `city_universities`，`run` 含 `input_city`、`city`、`date`、`output_dir`，并包含 `metrics`、`schools`、`warnings`、`outputs`。 |

### `city_universities.xlsx` 列

| 列名 | 来源或规则 |
| --- | --- |
| `学校名称` | 教育部名单的同名字段。 |
| `学校标识码` | 教育部名单的同名字段，按文本写入。 |
| `主管部门` | 教育部名单的同名字段。 |
| `所在地` | 教育部名单的同名字段，且与 `city_name` 完全一致。 |
| `办学层次` | 教育部名单的同名字段。 |
| `院校标签` | `985`、`211` 或空字符串。 |
| `办学性质` | `公办`、`民办`、`中外合作`、`境外机构` 或 `待核验`。 |

### `city_universities.json` 顶层字段

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `stage` | string | 固定为 `city_universities`。 |
| `city_context` | object | 完整城市上下文，供后续高校页面检索与地址处理继续传递。 |
| `run` | object | 本次运行的城市、日期和输出目录。 |
| `metrics` | object | `school_count` 与 `warning_count`。 |
| `schools` | array | 每所筛选出的高校记录。 |
| `warnings` | array | 办学性质为 `待核验` 的记录；可为空数组。 |
| `outputs` | object | `json` 与 `workbook` 的绝对输出路径。 |

## 高校地址批次

高校的 `city_universities`、`university_page_results` 与 `address_records` 顶层均携带 `city_context`。`city_universities.json` 是逐校检索和结果合并的基础名录；页面批次和公共地址记录继续原样传递该对象。

### 高校逐校检索结果

每所学校由负责该校的模型写入 `school_results/<school_identifier>.json`。模型负责根据检索和官网页面证据决定 `processing_status`；合并脚本只校验字段、学校覆盖与页面数量，不推断学校是否合并或仍在独立办学。

#### `completed` 记录

| 字段名 | 写入方 | 说明 |
| --- | --- | --- |
| `school_identifier` | 模型填写，脚本校验 | 必须复制自 `city_universities.schools` 中对应学校的标识码。 |
| `processing_status` | 模型决定并填写 | 固定为 `completed`。表示该校未被模型依据官方证据确认应跳过，后续仍进入地址处理。它不表示整个地址或 Excel 流程已完成。 |
| `pages` | 模型写入数组；页面对象由抓取脚本生成 | 按访问顺序保存页面对象，至少一页。模型决定是否继续检索、抓取哪些页面以及何时结束；数组中的每个页面对象必须原样采用 `fetch_university_page()` 输出。 |

`pages` 中页面对象的 `page_status`、`http_status`、`final_url`、地址候选和校区线索均由抓取脚本产生；模型不得自行推断或改写这些字段。网页返回 HTTP 错误或发生网络/Playwright 错误时，模型仍应保留该页面对象；只要学校未被确认需要跳过，仍填写 `completed`。

#### `skipped` 记录

| 字段名 | 写入方 | 说明 |
| --- | --- | --- |
| `school_identifier` | 模型填写，脚本校验 | 必须复制自 `city_universities.schools` 中对应学校的标识码。 |
| `processing_status` | 模型决定并填写 | 固定为 `skipped`。仅当模型已从官方证据确认学校不应继续按独立高校处理时使用。 |
| `skip_reason` | 模型判断并填写，脚本校验 | 仅允许 `merged` 或 `ceased_independent_operation`。 |
| `skip_reference` | 模型填写，脚本校验 | 支持该跳过结论的 HTTP(S) 官方证据页面。 |

`skipped` 记录不包含 `pages`，也不生成地址记录或地图请求。

### `address_records.metrics`

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `city_university_count` | integer | 城市高校名录中的学校数。 |
| `completed_school_count` | integer | 已完成官网检索的学校数。 |
| `skipped_school_count` | integer | 已确认合并或停止独立办学、未进入地址处理的学校数。 |
| `missing_school_count` | integer | 未提供逐校结果的学校数；成功构造时为 `0`。 |
| `page_count` | integer | 已完成学校保存的官网页面数。 |
| `item_count` | integer | 生成的公共地址记录数。 |
| `original_address_count` | integer | `original_address` 非空的记录数。 |
| `missing_original_address_count` | integer | `original_address` 为空、将按 `place_name` 查询地图的记录数。 |
| `warning_count` | integer | 同一校区存在多个不同官网地址的警告数。 |

### `schools` 记录字段

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `source_sequence` | string | 教育部名单的 `序号`。 |
| `school_name` | string | 学校名称。 |
| `school_identifier` | string | 学校标识码。 |
| `supervising_authority` | string | 主管部门。 |
| `location_city` | string | 所在地。 |
| `education_level` | string | 办学层次。 |
| `source_remark` | string | 教育部名单的备注。 |
| `school_tag` | string | `985`、`211` 或空字符串。 |
| `school_nature` | string | `公办`、`民办`、`中外合作`、`境外机构` 或 `待核验`。 |

### `warnings` 记录字段

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `source_sequence` | string | 对应学校的教育部名单序号。 |
| `school_name` | string | 对应学校名称。 |
| `reason` | string | 未匹配办学性质规则的备注说明。 |

## 官网页面地址证据

由 `query_city_core.fetch_official_page.fetch_official_page()` 生成。输入为已确认的 `url` 与 `official_domains`；输出不含 `schema_version`。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `stage` | string | 固定为 `official_page_address_evidence`。 |
| `requested_url` | string | 请求的官网 URL。 |
| `final_url` | string | 跳转后的最终 URL；失败时为空字符串。 |
| `http_status` | integer | null | HTTP 状态码。 |
| `page_status` | string | `ok`、`http_error` 或 `error`。 |
| `title` | string | 页面标题。 |
| `official_domains` | array | 已确认的官方域名。 |
| `address_evidence` | array | 从页面提取的地址证据。 |
| `links` | array | 页面链接，记录 `text` 与 `url`。 |
| `warnings` | array | 抓取或提取告警文本。 |

## 高校官网地址候选

由 `query-city-universities/scripts/fetch_official_universities.py` 的 `fetch_university_page()` 生成。输出不含 `schema_version`。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `stage` | string | 固定为 `address_candidates`。 |
| `requested_url`、`final_url`、`http_status`、`page_status`、`title`、`official_domains`、`warnings` | 与官网页面地址证据同名字段 | 保留页面抓取信息。 |
| `address_candidates` | array | 地址候选记录。 |
| `campus_hints` | array | 页面标题、地址证据或相关链接中提取的校区名称。 |
| `related_links` | array | 同官方域名内的相关页面，记录 `text`、`url`、`link_type`。 |

### `address_candidates` 记录字段

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `campus_hint` | string | 候选地址关联的校区名称；未识别时为空字符串。 |
| `address_text` | string | 清理后的地址文本。 |
| `source_text` | string | 页面证据文本的空白规范化版本。 |
| `association_method` | string | 校区关联方式。 |
| `extraction_method` | string | 地址证据的提取方式。 |
| `source_region` | string | 证据所在页面区域。 |
| `visible` | boolean | 证据在页面中是否可见。 |
