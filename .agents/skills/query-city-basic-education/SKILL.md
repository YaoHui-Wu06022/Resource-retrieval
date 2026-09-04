---
name: query-city-basic-education
description: "按中国城市的直接下级行政单位检索政府公开的非高校学校名录，提取学校与地址并生成区级和城市汇总 Excel。"
---

## 输入与运行条件

输入：一个中国城市。输出：该城市直接下级行政单位内的非高校学校信息。

- 环境未确认先询问；确认后全程使用同一环境。依赖：`beautifulsoup4`、`lxml`、`pandas`、`openpyxl`、`xlrd`、`PyMuPDF`；Word 还需 LibreOffice。
- `requirements.txt` 只锁定 `query-city-core` 版本；其余依赖按上条安装，版本由运行环境管理。
- 城市查询与地址处理从环境变量或 `.env` 读取 `AMAP_KEY`；扫描图片/PDF 的表格解析使用 MinerU API，凭据为 `.env` 中的 `MINERU_ACCESS_KEY`/`MINERU_SECRET_KEY`（OpenXLab AK/SK，运行时换取 JWT，不写入输出）。
- 缺依赖、密钥或公共组件时停下说明缺项；不自装、不写临时脚本复制固定逻辑。
- 执行约定：命令示例的相对路径相对 skill 根目录；文中脚本命令为简写，实际执行按仓库 AGENTS.md 约定加解释器（`conda run --no-capture-output -n py3.10 python -X utf8 ...`）。

全部输出写入 `output/<标准城市名>/<YYYY-MM-DD>/Basic_Education/<HHMMSS>/`。每次调用用新 `<HHMMSS>`，重新检索并生成全部结果，不覆盖同日旧结果，旧目录保留。

## 执行边界与 Agent 分工

固定处理统一调用下表脚本（`list-links` 按需；`address.process` 串行执行）：

| 用途 | 命令 |
| --- | --- |
| 标准化城市、取下级行政单位 | `python -m query_city_core.address.city` |
| （可选）栏目页链接抓取 | `scripts/school_government_flow.py list-links` |
| 保存入选来源文件 | `scripts/school_government_flow.py download` |
| 保存名录链接的同构详情页 | `scripts/school_government_flow.py collect-details` |
| 检查来源、生成提取计划 | `scripts/school_government_flow.py inspect` |
| 扫描 PDF 逐页解析为视觉结果 | `scripts/school_government_flow.py mineru-parse` |
| 整档扫描 PDF 页表摘要（可选） | `scripts/school_government_flow.py mineru-inspect` |
| 复核提取计划行覆盖 | `scripts/school_government_flow.py preview` |
| 按配置批准提取规则 | `scripts/review.py <提取计划> <复核配置>` |
| 按已复核计划提取学校 | `scripts/school_government_flow.py extract` |
| 规范化地址与地图兜底 | `python -m query_city_core.address.process` |
| 生成区级与城市工作簿 | `scripts/build_excel.py` |

- Agent 负责来源检索、质量与覆盖判断、提取计划复核；脚本负责类型规范、去重、地址路由、排序与工作簿格式。
- Agent 按 `subdivisions` 顺序逐个完成第 2-4 节，再串行执行第 5 节地址处理并生成第 6 节工作簿。

## 1. 取得行政单位

```powershell
$runDate = Get-Date -Format yyyy-MM-dd
$runTime = Get-Date -Format HHmmss
$runDir = 'output/<标准城市名>/' + $runDate + '/Basic_Education/' + $runTime
New-Item -ItemType Directory -Force $runDir | Out-Null
python -m query_city_core.address.city --city <用户城市>
```

`<标准城市名>` 用城市组件返回的规范名称，如 `深圳市`。

读输出中的标准城市名与 `subdivisions`。在 `$runDir` 下按 `subdivisions[].name` 建同名目录，之后依次处理每个目录；不得增删、合并、改名或继续查询更低一级行政单位。

## 2. 检索并保存政府来源

**检索规则**

- 检索来源：采用政府或教育部门发布、且正文/附件/分页实际含学校名录的来源；通知仅在含名录时采用。禁用地图、百科、择校网站等第三方学校信息。
- 来源形态优先文本：优先使用（网页表格/Excel/CSV/Word/可提取文本 PDF），没有信息的情况下兜底使用扫描图片/PDF，并登记 `source_form_reason = no_text_alternative`。
- 检索起点按学段发布层级分两类，均优先当年/去年：
  - 高中：市级优先——市级教育部门 → 市招生考试机构/中考服务平台 → 市政府数据平台；
  - 幼儿园/小学/初中：区级优先——本区教育部门 → 区政府门户；缺失时继续回退到上级教育部门 → 市招生考试机构/中考服务平台 → 市政府数据平台。
- 只有超两年旧名录时，须再核对当年/去年的资源，确实没有则标 `partial` 并保留旧名录。
- 层级回退不可省略：某一学段在首选层级找不到可用名录时，必须沿该学段路径继续核验。市级名录若带“校址所在区 / 行政区”等可区分字段，应按行政单位过滤后作为该单位来源采用，不能因名录覆盖全市而放弃采用；市级名录若没有可区分行政单位的字段，不能整表归入任一行政单位，须在 `coverage_notes` 说明并继续找区级或可拆分来源。
- `no_official_source`/`source_unusable` 只表示按该学段首选层级与回退层级完成核验后仍无可用政府名录，不等于该行政单位没有该学段学校；不得把“某层级没有发布名录”写成“该区没有该类学校”。
- 四类必查：幼儿园、小学、初中、高中。来源列出的其他非高校类型（一贯制、完全中学、特殊教育、中等职业、技工、专门学校等）一并纳入。
- 一贯制/完中按覆盖学段计入四类覆盖：完全中学 = 初中 + 高中；九年一贯制 = 小学 + 初中；十二年一贯制 = 小学 + 初中 + 高中；十五年一贯制 = 幼儿园 + 小学 + 初中 + 高中。`school_type_coverage`、`covered_school_types` 据此填写，不按名称字面推断。

凡 `school_type_coverage` 存在非 `covered` 状态（`partial`、`no_official_source`、`source_unusable`），必须在 `government_source.json` 顶层 `coverage_notes` 中按学段写明已核验层级与结论，供复核判断缺口是否合理。

访问兜底：`download`、`collect-details`、`list-links` 内置 urllib → curl 直连并记录尝试；需执行脚本或登录的内容才用浏览器并同样记录。访问失败 ≠ 没有官方来源。

**保存来源文件（按需）**

- `list-links`：栏目页筛候选。输入 `directory_link_manifest.json` （items 给 `url`，可选 `link_pattern`、`allowed_domain`）→ `directory_links.json`，复核后收录。
- `download`：保存入选来源。输入 `source_download_manifest.json` （items 给 `file`、`url`，可选 `allowed_domain`）→ 本地文件 + 写回清单。
- `collect-details`：名录页链接到同构详情页时使用

  `collect-details --input <名录页.html> --link-selector <选择器> --output-dir <详情页目录> --manifest <清单.json> --allowed-domain <域名>`
  
  返回非零或 `errors` 非空时先复核。

三个命令默认同主机串行，可用 `--max-workers`、`--host-max-workers`、 `--host-min-interval` 调整；节流只约束单进程。

清单字段、GBK 附件名与解压限制细节见 [政府来源结果格式](references/government-source-format.md)。

每个行政单位必须写明幼儿园、小学、初中、高中的覆盖状态，找不到资料也要写明。

## 3. 检查并复核提取计划

命令：`scripts/school_government_flow.py inspect --sources <government_source.json> --output <extraction_plan.json>` → `extraction_plan.json`(待复核)

复核表定位、列、固定值、向下填充与排除行：

- 含 `<thead>` 的名录页由 `inspect` 自动识别；校名含 `（九年一贯制）` 等官方标记自动判型，无标记的多学段行人工补官方类型标签。
- 单一覆盖类型且无类型列时自动预填固定类型；多学段来源不预填。
- 批准前运行 `preview --plan <extraction_plan.json>`；缺行、重叠或待批准时非零 = 复核未通过。
- 正确规则设 `approved = true`，来源设 `review_status = ready`； 不手工抄写最终记录。
- 图片/扫描 PDF（`source_form_reason = no_text_alternative`）按[政府来源结果格式](references/government-source-format.md)的视觉一节执行：用 `mineru-parse` 生成 `<原文件名>.vision.json` 并写回该来源 `derived_files`；缺 MinerU 凭据时不创建该文件、不运行本地 OCR，显式按 `no_vision_capability` 跳过。
- 规则批准使用 `scripts/review.py <extraction_plan.json> <plan_config_<区>.json>`；复核配置固定 `district`、`approved_pdf_pages`（高中可选）与 `files[].rules[]`（页/表定位、校名列、地址列、固定类型与性质、排除行、向下填充）。

## 4. 提取学校记录

- 输入：已复核的 `extraction_plan.json`
- 命令：`scripts/school_government_flow.py extract --plan <extraction_plan.json> --output <address_records.json>`
- 输出：`address_records.json`

仅当 `stage = address_records` 且 `metrics.error_count = 0` 才继续。

记录须含学校名称、原始地址、学校类型、办学性质、发布日期、行政单位、可定位来源；`source_nature` 固定为 `government_information`。来源无地址时留空，不推断、不编造。

脚本按「校名 + 原始地址」合并并按学段去重，保留官方类型标签 （小学 + 九年一贯制 → 九年一贯制；不同官方标签并存）。

## 5. 处理地址

- 约束：串行执行，同一时间只允许一个 `address.process` 进程。
- 输入：`address_records.json`
- 命令：`python -m query_city_core.address.process --input <address_records.json> --output <processed_address_records.json>`
- 输出：`processed_address_records.json`

地址规则：政府完整地址直接采用；地址为空，或只有区/街道/片区且不含小区、楼栋、村等具体地点词时，按学校名在当前行政单位内做 POI 兜底；已含具体地点信息时直接采用官方地址。目标城市冲突或无合格结果时最终地址留空，保留在输出中供复检。

## 6. 生成最终工作簿

- 输入：`Basic_Education` 目录（各行政单位的 `processed_address_records.json`）
- 命令：`scripts/build_excel.py --input-dir <Basic_Education目录> --output <基础教育学校查询_<标准城市名>_<YYYY-MM-DD>.xlsx>`
- 输出：每个行政单位一份区级工作簿 + 一份城市总表（“学校信息”总表 + 各区工作表）

区级工作簿含「学校信息」「异常校」两表：学校信息只输出最终地址非空的记录；异常校列最终地址为空的学校及异常原因。去重、类型顺序、区内排序、按区拼接与展示格式以脚本结果为准，不由 Agent 手工调整。

## 完成检查

- `subdivisions` 每个行政单位都有返回结果或明确的无来源状态，无遗漏、无重复目录。
- 四类学校均完成独立检索，覆盖缺口已写入 `government_source.json`。
- `school_type_coverage` 中每个非 `covered` 学段都在 `coverage_notes` 中写明已完成检索的层级与结论；缺失说明视为复核未通过。
- 含人工分区规则的提取计划已运行 `preview` 且无缺行、无重叠。
- 每个 `needs_vision` 来源已生成 `<原文件名>.vision.json` 并加入 `derived_files` 重跑检查；无视觉配置时才显式 `no_vision_capability` 跳过。
- 每个进入汇总的行政单位都有合法的 `address_records.json` 与 `processed_address_records.json`；区级工作簿含两个工作表且异常原因非空。
- 城市总表行数 = 各区行数之和，输出行最终地址均非空；空地址记录保留在 `processed_address_records.json` 供复检，不进工作簿。
- 最终工作簿可打开，表与列符合约定。

最终回复只说明标准城市名、行政单位总数及各状态数量、来源总数、最终地址行数和最终文件绝对路径，不展开逐区检索过程。
