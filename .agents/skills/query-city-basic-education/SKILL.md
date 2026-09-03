---
name: query-city-basic-education
description: "按中国城市的直接下级行政单位检索政府公开的非高校学校名录，提取学校与地址并生成区级和城市汇总 Excel。"
---

## 输入与运行条件

输入：一个中国城市。输出：该城市直接下级行政单位内的非高校学校信息。

- 环境未确认先询问；确认后全程使用同一环境。依赖：`beautifulsoup4`、`lxml`、`pandas`、`openpyxl`、`xlrd`、`PyMuPDF`；Word 还需 LibreOffice。
- `requirements.txt` 只锁定 `query-city-core` 版本；其余依赖按上条安装，版本由运行环境管理。
- 城市查询与地址处理从环境变量或 `.env` 读取 `AMAP_KEY`。
- 缺依赖、密钥或公共组件时停下说明缺项；不自装、不写临时脚本复制固定逻辑。
- 执行约定：命令示例的相对路径相对 skill 根目录；非交互 Python 命令按仓库 AGENTS.md 的运行约定执行。

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
| 复核提取计划行覆盖 | `scripts/school_government_flow.py preview` |
| 按已复核计划提取学校 | `scripts/school_government_flow.py extract` |
| 规范化地址与地图兜底 | `python -m query_city_core.address.process` |
| 生成区级与城市工作簿 | `scripts/build_excel.py` |

Agent 负责来源检索、质量与覆盖判断、提取计划复核；脚本负责类型规范、去重、地址路由、排序与工作簿格式。

本 skill 不按行政单位分派：由同一执行 Agent 按 `subdivisions` 顺序逐个完成第 2-4 节，处理一个行政单位时只写它的目录；再串行执行第 5 节地址处理并生成第 6 节工作簿。下文“执行 Agent”即运行本 skill 的 Agent。

## 1. 取得行政单位

```powershell
$runDate = Get-Date -Format yyyy-MM-dd
$runTime = Get-Date -Format HHmmss
$runDir = 'output/<标准城市名>/' + $runDate + '/Basic_Education/' + $runTime
New-Item -ItemType Directory -Force $runDir | Out-Null
python -m query_city_core.address.city --city <用户城市>
```

读输出中的标准城市名与 `subdivisions`。在 `$runDir` 下按 `subdivisions[].name` 建同名目录，之后依次处理每个目录；不得增删、合并、改名或继续查询更低一级行政单位。

## 2. 检索并保存政府来源

**检索规则（Agent 判断）**

- 只采用政府或教育部门发布、且正文/附件/分页实际含学校名录的来源；通知仅在含名录时采用。禁用地图、百科、媒体、自媒体、择校网站和第三方学校数据库。
- 来源形态优先文本：同一名录同时存在网页表格、Excel、CSV、Word 或
  可直接提取文本的 PDF，与扫描图片/PDF 时，必须优先采用文本形态；
  仅当确认无文本替代时才采用需要视觉的来源，并在
  `government_source.json` 对应来源项填 `source_form_reason` 为
  `no_text_alternative`。
- 按「本区教育部门 → 区政府门户 → 上级教育部门 → 政府数据平台」检索；优先当年、去年，覆盖不足再扩前年。
  若某类只有超过两年的基本情况名录，仍须再核对当年/去年的招生计划、办学许可或基本信息名单；
  确实没有时该类覆盖状态如实标 `partial` 并保留旧名录。
- 四类必查：幼儿园、小学、初中、高中。来源列出的其他非高校类型（一贯制、完全中学、特殊教育、中等职业、技工、专门学校等）一并纳入。
- 一贯制/完中按覆盖学段计入四类覆盖：完全中学 = 初中 + 高中；九年一贯制 = 小学 + 初中；十二年一贯制 = 小学 + 初中 + 高中；十五年一贯制 = 幼儿园 + 小学 + 初中 + 高中。`school_type_coverage`、`covered_school_types` 据此填写，不按名称字面推断。

访问兜底：`download`、`collect-details`、`list-links` 内置 urllib → curl 直连并记录尝试；需执行脚本或登录的内容才用浏览器并同样记录。访问失败 ≠ 没有官方来源。

**保存来源文件（按需执行，含输入输出）**

`list-links`（栏目页筛候选）

- 输入：`directory_manifest.json`，`stage = directory_link_manifest`，items 给 `url`，顶层可选 `link_pattern`、`allowed_domain`
- 命令：`scripts/school_government_flow.py list-links --input <manifest> --output <links.json>`
- 输出：`directory_links.json`（候选链接）；复核后决定收录

`download`（保存入选来源）

- 输入：`source_download_manifest.json`，`stage = source_download_manifest`，items 给 `file`、`url`，顶层可选 `allowed_domain`
- 命令：`scripts/school_government_flow.py download --manifest <manifest> --output-dir <行政单位目录>`
- 行为：保存 HTML/Excel(`.xls/.xlsx/.xlsm`)/CSV/Word/PDF/图片；分页全存，附件保留原名原格式；清单原地写回每项 `final_url`、`http_status`、`size_bytes`、`access_attempts`，失败项进顶层 `errors`
- zip 附件下载后自动解压其中可读文件，清单写回 `extracted_files`（GBK 中文文件名自动修复）；
  入选来源从解压结果中选取并写入 `government_source.json` 的 `local_files`，不要把 zip 本身作为来源。
- zip：`.zip` 附件落盘后自动安全解压一层，只提取 HTML/Word/Excel/CSV/PDF/图片等可读来源，按 zip 内相对路径保存，zip 原件保留；成功项登记 `extracted_files`（可含 `skipped_entries`），解压失败进 `errors` 并返回非零，压缩包保留供人工处理
- 输出：本地文件 + 写回结果的清单；随后把普通文件或清单中 `extracted_files` 登记的路径写入 `government_source.json` 的 `local_files`，并补 `local_file_urls`、`access_attempts`

`collect-details`（名录页链接到同构详情页时）

- 输入：本地名录 HTML + 已复核的详情链接 CSS 选择器 + 允许域名
- 命令：`scripts/school_government_flow.py collect-details --input <名录页.html> --link-selector <选择器> --output-dir <详情页目录> --manifest <详情页清单.json> --allowed-domain <域名>`
- 输出：详情页文件 + 清单（`local_file` 与逐页网址）；返回非零或 `errors` 非空时先复核再继续，不得把访问失败当作学校不存在

并发：三命令默认同主机串行（并发 1、间隔 0.3 秒），跨主机并行不超过 `--max-workers`；可用 `--max-workers`、`--host-max-workers`、`--host-min-interval` 调整。节流只约束单进程。

写 `government_source.json` 前读取 [政府来源结果格式](references/government-source-format.md)。每个行政单位必须写明幼儿园、小学、初中、高中的覆盖状态；找不到资料也要写明。

## 3. 检查并复核提取计划

- 输入：`government_source.json`
- 命令：`scripts/school_government_flow.py inspect --sources <government_source.json> --output <extraction_plan.json>`
- 输出：`extraction_plan.json`（待复核）

复核内容：脚本识别的表格、列、固定值、向下填充、排除行是否正确。

- 含 `<thead>` 表头的门户名录页（如越秀区教育机构一览）由 `inspect` 自动识别并生成规则。
- 校名含官方一贯制标记（`（九年一贯制）` 等）的行自动判型；无标记的多学段行仍需人工填官方类型标签。
- 批准前运行 `scripts/school_government_flow.py preview --plan <extraction_plan.json>`
  检查是否有未被任何规则覆盖或重复命中的数据行；非零返回表示复核未通过。

单一覆盖类型且无类型列时脚本自动预填固定学校类型；九年一贯制、完全中学、十二年一贯制等多学段来源不会预填，需人工填官方类型标签。

正确规则设 `approved = true`，来源设 `review_status = ready`；不得手工抄写最终学校记录。

PDF/图片标记 `needs_vision` 时按参考文档的视觉分支处理：有视觉能力则生成视觉结果并重跑检查；否则该来源按 `no_vision_capability` 跳过，不运行本地 OCR。进入视觉分支的来源须已在 `government_source.json` 登记 `source_form_reason = no_text_alternative`，未登记的视觉来源视为检索未完成。

## 4. 提取学校记录

- 输入：已复核的 `extraction_plan.json`
- 命令：`scripts/school_government_flow.py extract --plan <extraction_plan.json> --output <address_records.json>`
- 输出：`address_records.json`

仅当 `stage = address_records` 且 `metrics.error_count = 0` 才继续。

记录须含学校名称、原始地址、学校类型、办学性质、发布日期、行政单位、可定位来源；`source_nature` 固定为 `government_information`。来源无地址时留空，不推断、不编造。

脚本按「校名 + 原始地址」合并记录，按覆盖学段去重并保留官方类型标签（如 小学 + 九年一贯制学校 → 九年一贯制学校；九年一贯制学校 + 完全中学 → 保留两者）。

## 5. 处理地址

- 约束：执行 Agent 串行调用，同一时间只允许一个 `address.process` 进程。当前高德 key 每秒上限少于 3 次，公共层按 1 秒窗口 2 次执行；两区并行即超限（2 × 2 > 3）。更换 key 档位后再调整公共层限流参数。
- 输入：`address_records.json`
- 命令：`python -m query_city_core.address.process --input <address_records.json> --output <processed_address_records.json>`
- 输出：`processed_address_records.json`

地址规则：政府完整地址直接采用；地址为空，或只有区/街道/片区且不含小区、楼栋、村等具体地点词时，按学校名在当前行政单位内做 POI 兜底；已含具体地点信息时直接采用官方地址。目标城市冲突或无合格结果时最终地址留空，保留在输出中供复检。

## 6. 生成最终工作簿

- 输入：`Basic_Education` 目录（各行政单位的 `processed_address_records.json`）
- 命令：`scripts/build_excel.py --input-dir <Basic_Education目录> --output <基础教育学校查询_<标准城市名>_<YYYY-MM-DD>.xlsx>`
- 输出：每个行政单位一份区级工作簿 + 一份城市总表（“学校信息”总表 + 各区工作表）

区级工作簿含「学校信息」「异常校」两表：学校信息只输出最终地址非空的记录；异常校列最终地址为空的学校及异常原因。去重、类型顺序、区内排序、按区拼接与展示格式以脚本结果为准，不由 Agent 手工调整。

学校信息表列：序号、行政单位、学校名称、学校类型、办学性质、发布日期、
查询日期、地址、地址获取方式、地图匹配状态、信息来源。异常校表列：
序号、行政单位、学校名称、学校类型、办学性质、发布日期、异常原因、
信息来源、查询日期。

## 完成检查

- `subdivisions` 每个行政单位都有返回结果或明确的无来源状态，无遗漏、无重复目录。
- 四类学校均完成独立检索，覆盖缺口已写入 `government_source.json`。
- 含人工分区规则的提取计划已运行 `preview` 且无缺行、无重叠。
- 每个 `needs_vision` 来源均已登记 `source_form_reason = no_text_alternative`，确认过无文本替代。
- 每个进入汇总的行政单位都有合法的 `address_records.json` 与 `processed_address_records.json`。
- 每个区级工作簿含两个工作表，异常校每行异常原因非空。
- 城市总表行数 = 各区行数之和，输出行最终地址均非空。
- 最终地址为空的记录保留在 `processed_address_records.json` 供复检，不进工作簿。
- 最终工作簿可打开，表与列符合约定。

最终回复只说明标准城市名、行政单位总数及各状态数量、来源总数、最终地址行数和最终文件绝对路径，不展开逐区检索过程。
