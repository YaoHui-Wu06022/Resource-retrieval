---
name: query-city-basic-education
description: "按中国城市的直接下级行政单位检索政府公开的非高校学校名录，提取学校与地址并生成区级和城市汇总 Excel。"
---

## 输入与运行条件

输入城市 → 输出该市各直接下级行政单位（`subdivisions`）内非高校学校信息。

- 环境未确认先询问；确认后全程使用同一环境。
- 依赖：`beautifulsoup4`/`lxml`/`pandas`/`openpyxl`/`xlrd`/`PyMuPDF`（Word 另需 LibreOffice）；`requirements.txt` 只锁 `query-city-core` 版本。
- 密钥在 `.env` 或环境变量：`AMAP_KEY`（地址/地图）、`MINERU_ACCESS_KEY`+`MINERU_SECRET_KEY`（扫描件解析；运行时换 JWT，不落盘、不写日志）。
- 缺依赖/密钥/公共组件即停下说明缺项；不自装依赖、不写一次性临时脚本复制固定逻辑。
- 输出到 `output/<标准城市名>/<YYYY-MM-DD>/Basic_Education/<HHMMSS>/`；每次调用新建 HHMMSS，不覆盖旧结果。

## 流程与分工

| 步骤 | 命令/方式 |
| --- | --- |
| 行政单位 | `python -m query_city_core.address.city` |
| 来源保存 | `scripts/school_government_flow.py` 的 `list-links`/`download`/`collect-details`（按需，见 §2） |
| 扫描件转录 | `scripts/school_government_flow.py` 的 `mineru-parse`/`mineru-inspect`（见 §3 与参考文档视觉节） |
| 提取计划 | `scripts/school_government_flow.py inspect`（见 §3） |
| 计划复核 | `scripts/review.py` 批准规则 → `scripts/school_government_flow.py preview` 复核行覆盖（见 §3） |
| 记录提取 | `scripts/school_government_flow.py extract`（见 §4） |
| 地址规范化 | `python -m query_city_core.address.process` （串行） |
| 工作簿 | `scripts/build_excel.py`（见 §6） |
| 质量闸门 | `scripts/school_quality_check.py --input-dir <运行目录>` |

来源身份、学段覆盖与计划复核由 Agent 依官方证据完成；类型规范、去重、地址路由、排序与工作簿格式由脚本完成。`government_source.json` 与 `sources/` 原始文件只能由 Agent 确认后写入。

## 1. 行政单位

```powershell
$runDate = Get-Date -Format yyyy-MM-dd; $runTime = Get-Date -Format HHmmss
$runDir = "output/<标准城市名>/$runDate/Basic_Education/$runTime"; New-Item -ItemType Directory -Force $runDir | Out-Null
python -m query_city_core.address.city --city <用户城市>
```

用城市组件返回的规范名与 `subdivisions`；在其下按 `subdivisions[].name` 建同名目录，依次处理；不增删/合并/改名目录，不查更低一级。

## 2. 检索与保存政府来源

**规则**

- 只用政府/教育部门发布且正文、附件或分页实际含名录的来源；通知仅在含名录时采用；禁用地图、百科、择校等第三方。
- 形态优先文本（网页表/Excel/CSV/Word/可提取 PDF）；确无文本替代才用扫描件，来源标 `source_form_reason = no_text_alternative`。
- 时效与层级，均优先当年/去年：高中走市级（市教育部门 → 市招考/中考平台 → 市数据平台）；幼儿园/小学/初中走区级（区教育部门 → 区政府门户），缺位时回退市级路径。
- 超两年旧名录须再核当年/去年，确无才可标 `partial` 并保留。
- 层级回退不可省略；市级名录含“校址所在区”等字段→按区过滤后采用；无该字段→不得整表归入某区，在 `coverage_notes` 说明并继续找区级/可拆分来源。
- `no_official_source`/`source_unusable` = 完成该学段层级回退后仍无可用名录，≠ 该区无此类学校。
- 四类必查：幼儿园、小学、初中、高中；来源中的其它类型（一贯制、完中、特教、中职、技工、专门学校等）一并纳入。
- 一贯制覆盖映射（写 `school_type_coverage`/`covered_school_types`，不按名称猜）：完全中学=初中+高中；九年一贯=小学+初中；十二年一贯=小学+初中+高中；十五年一贯=幼儿园+小学+初中+高中。
- 任何非 `covered` 学段必须在 `coverage_notes` 写明“已核验层级+结论”。
- 访问用内置 urllib→curl 直连并记录尝试；需脚本/登录才用浏览器并同样记录；访问失败 ≠ 无官方来源。

**保存**：`list-links` 筛栏目候选 → 复核后收录；`download` 存来源并回写清单；`collect-details` 存名录链接的同构详情页；三个命令默认同主机串行，可用 `--max-workers/--host-max-workers/--host-min-interval` 调节。清单格式与 zip/GBK 细节见 [政府来源结果格式](references/government-source-format.md)。

## 3. 检查与复核提取计划

- `inspect` 自动识别 `<thead>` 表头；校名带官方标记（如 `（九年一贯制）`）自动判型；单类型且无类型列自动预填固定类型；多学段来源不预填。
- Agent 复核列定位、固定值、向下填充与排除行；规则 `approved=true`、来源 `review_status=ready`；不手工抄写最终记录。
- `scripts/review.py <plan.json> <plan_config_<区>.json>` 按配置批准规则；配置结构：`district`、`approved_pdf_pages`（报考指南可选）、`files[{file, location_key, rules[{kind, location 或pages("15-33"), name_cols, addr_col, fixed_type/fixed_nature/type_col/nature_col, required, fill_down, exclude_rows}]}]`；`pages` 自动展开，缺省表头按视觉 JSON 首页自动判定；报考指南只保留确实含本区单元格的页/表规则。
- 批准后必须 `preview`：缺行、重叠或待批准非零 = 复核未通过。
- 扫描件按参考文档视觉节执行：`mineru-parse` 逐页生成 `<原名>.pdf.vision.json` 并写回该来源 `derived_files`；无 MinerU 凭据时不创建、不本地 OCR，显式按 `no_vision_capability` 跳过。

## 4. 提取记录

`extract --plan <extraction_plan.json> --output <address_records.json>` 输出地址记录；仅当 `stage=address_records` 且 `metrics.error_count=0` 才继续。记录须含学校名称、原始地址、学校类型、办学性质、发布日期、行政单位、可定位来源；`source_nature=government_information`；来源无地址留空，不推断、不编造。脚本按「校名+原始地址」合并并按学段去重，保留官方类型标签（如小学+九年一贯制→九年一贯制）。

## 5. 处理地址

约束：`address.process` 串行，同一时间仅一个进程。政府完整地址直接采用；地址为空或仅区/街道/片区且不含小区、楼栋、村等具体地点词→按校名在所在区内做 POI 兜底；已含具体地点词直接采用官方地址。目标城市冲突或无合格结果→最终地址留空，记录保留在输出中供复检。

## 6. 生成工作簿

运行 `scripts/build_excel.py --input-dir <Basic_Education目录> --output <总表.xlsx>`：读各单位 `processed_address_records.json`，输出每区工作簿 + 城市总表。区级工作簿含「学校信息」（最终地址非空）与「异常校」（最终地址为空及异常原因）两表；去重、排序、列序等以脚本结果为准，Agent 不手工调整。

## 完成检查

- `subdivisions` 全部有结果或明确无来源状态；目录不重不漏。
- 四类均完成独立检索；非 `covered` 已在 `coverage_notes` 写明，缺失即不通过。
- 含人工配置的计划已 `preview` 且 0 缺行/0 重叠/0 待批准。
- 每个 `needs_vision` 来源已生成视觉文件并登记 `derived_files`；无凭据时显式跳过。
- 每区 `address_records.json`/`processed_address_records.json` 合法；工作簿双表存在且异常原因非空。
- 城市总表行数 = 各区行数之和；学校信息行最终地址非空；空地址记录保留在 processed 文件，不进工作簿。
- 交付前运行 `school_quality_check.py --input-dir <运行目录>` 且 `passed = true`：每区来源清单合法（非 `covered` 学段已写 `coverage_notes`）、提取计划的来源均已复核且有已批准规则、`address_records.json` 与 `processed_address_records.json` 阶段合法。

最终回复只给：标准城市名、行政单位总数及各状态数量、来源总数、最终地址行数、最终文件绝对路径，不展开逐区过程。
