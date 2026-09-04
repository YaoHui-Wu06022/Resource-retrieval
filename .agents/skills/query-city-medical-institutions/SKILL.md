---
name: query-city-medical-institutions
description: "按中国城市的直接下级行政单位检索政府公开的持证/备案医疗机构（医院、诊所、门诊部、社康中心、医学实验室等），整理名称、类型、级别和地址并生成区级和城市汇总 Excel。"
---

## 输入与运行条件

输入：一个中国城市。输出：该城市各直接下级行政单位持证/备案医疗机构的地址信息工作簿（每区「机构信息」+「异常机构」两个工作表与一份城市总表）。

- 环境未确认先询问；确认后全程使用同一环境。依赖 `openpyxl`、`query-city-core`；在线查询页需浏览器采集时另备 Playwright。
- 本 Skill 主要使用政府官方地址，默认不依赖高德补充查询；需要对空地址/异常地址做地图兜底时才从环境变量或 `.env` 读取 `AMAP_KEY`。
- 缺依赖、浏览器或公共组件时停下说明缺项；不自装、不另写临时脚本复制固定逻辑。

全部输出写入 `output/<标准城市名>/<YYYY-MM-DD>/Medical_Institutions/<HHMMSS>/`，每次调用用新目录，不覆盖旧运行结果。

## 执行边界与 Agent 分工

固定处理统一调用下表脚本，不另写临时脚本拆分、转换或组装来源输出：

| 用途 | 命令 |
| --- | --- |
| 标准化城市、取下级行政单位 | `python -m query_city_core.address.city` |
| （可选）栏目页链接抓取 | `scripts/medical_government_flow.py list-links` |
| 保存入选来源文件 | `scripts/medical_government_flow.py download` |
| 保存名录链接的同构详情页 | `scripts/medical_government_flow.py collect-details` |
| 检查来源、生成提取计划 | `scripts/medical_government_flow.py inspect` |
| 提取机构地址 | `scripts/medical_government_flow.py extract` |
| 规范化地址与可选地图兜底 | `python -m query_city_core.address.process` |
| 生成区级与城市工作簿 | `scripts/build_excel.py` |

- Agent 负责来源检索、机构类别覆盖核对、提取计划复核与来源质量判断；固定脚本负责按官方字段解析、地址拆分、去重、排序与工作簿格式。
- Agent 按 `subdivisions` 顺序逐区完成第 2-4 节，处理一个行政单位时只写它的目录；第 5 节地址处理串行，最后执行第 6 节生成工作簿。`government_source.json` 与 `sources/` 下的原始文件只能由 Agent 人工确认后写入。

## 1. 取得行政单位并建立目录

```powershell
$runDate = Get-Date -Format yyyy-MM-dd
$runTime = Get-Date -Format HHmmss
$runDir = 'output/<标准城市名>/' + $runDate + '/Medical_Institutions/' + $runTime
New-Item -ItemType Directory -Force $runDir | Out-Null
python -m query_city_core.address.city --city <用户城市> > "$runDir/city_context.json"
```

读输出中的标准城市名与 `subdivisions`，在运行目录下按 `subdivisions[].name` 建同名目录；不得增删、合并、改名或继续查询更低一级行政单位。

## 2. 逐行政单位检索并保存官方来源

**检索规则**

- 只采用政府卫健委/区政府发布的持证、登记或备案名单，正文或附件须实际含医疗机构记录；禁用地图、百科、媒体与第三方机构库。
- 机构类别覆盖医院、诊所、门诊部、社区卫生服务中心/站、村卫生室、医学检验实验室等，每类都要有官方来源或明确“无公开名单”结论。
- 按“区级全量 → 市级 → 省级”找名单：区级看区卫健局/区政府门户的公示公告、政务公开重点领域与便民查询，“发证/登记发证/在册”一览表才是全量名单，个案备案公示只作证据不作全量；市级看卫健委发证批次（多个批次取最新“数据截至”一期）与医疗机构检索/查询平台（可按行政区过滤，可作跨区来源复用）；省级卫健委/中医药局发证名单用于补充。统一搜索平台只用于定位页面，不作为来源。
- 市级跨区来源在提取时按行行政区字段剔除不属于当前行政单位的行，Agent 复核规则时须确认该字段映射正确。
- 访问失败不等于无来源；在线查询页无法直接下载时用浏览器采集证据。确实没有全量名单时写 `no_official_source`，禁止凭空补记录或把“没搜到”当结论。

**保存来源与写清单**

- 需要时用 `list-links` / `download` / `collect-details` 子命令保存栏目链接、附件或同构详情页，文件放入 `<行政单位目录>/sources/`。
- 把来源写入 `<行政单位目录>/government_source.json`，字段见 [来源格式](references/medical-source-format.md)；顶层含完整 `city_context` 与 `administrative_unit`（原样取自 `city_context.subdivisions` 的一项）；`status` 只允许 `ready` / `missing` / `no_official_source`，`ready` 来源必须已有本地文件。

## 3. 检查并复核提取计划

- 命令：`scripts/medical_government_flow.py inspect --sources <government_source.json> --output <extraction_plan.json>`，每个行政单位目录单独执行。
- 复核规则列、表头映射与对象列表字段；正确的规则设 `approved = true`，来源设 `review_status = ready`。

## 4. 提取机构记录

- 命令：`scripts/medical_government_flow.py extract --plan <extraction_plan.json> --output <address_records.json>`，每个行政单位目录单独执行。
- 仅当 `stage = address_records` 且 `metrics.error_count = 0` 才继续。公共引擎按官方字段保留机构名称、类型、级别，按执业地点拆分地址，剔除明确外市地址段及不属于当前行政单位的行；无地址记录保留在结果中供异常表使用。

## 5. 处理地址

- 命令：`python -m query_city_core.address.process --input <address_records.json> --output <processed_address_records.json>`；执行 Agent 串行调用，同一时间只允许一个进程。
- 官方完整地址直接采用；规范化冲突但官方地址仍可用的记录由 Excel 阶段保留官方地址。最终工作簿不依赖地图查询结果。

## 6. 生成最终工作簿

- 命令：`scripts/build_excel.py --input-dir <运行目录> --output <医疗机构信息_<标准城市名>_<YYYY-MM-DD>.xlsx>`
- 输出每个行政单位目录一份区级工作簿与运行目录一份城市总表：区级工作簿含「机构信息」「异常机构」两表；城市总表为“机构信息”汇总表 + 各区工作表，不含异常机构表。
- 异常机构行由脚本从各 `processed_address_records.json` 推导：最终地址为空且无可用官方原文（或带 `abnormal_reason`）的记录进入异常机构表，不另设异常清单文件。
- 「机构信息」表列：序号、行政单位、机构名称、机构类型、机构级别、查询日期、地址、地址获取方式、地图匹配状态、信息来源。「异常机构」表列：序号、行政单位、机构名称、机构类型、机构级别、异常原因、信息来源、查询日期。类型与级别保留官方原文，来源没有时留空；机构级别为“未定级/无定级/无级别”时工作簿该列显示为空。

## 完成检查

- `subdivisions` 每个行政单位都有来源清单与合法的 `address_records.json`、`processed_address_records.json`；`ready` 来源均有本地文件，清单顶层含完整 `city_context` 与 `administrative_unit`。
- 每条输出记录可追溯到原始来源文件/页面与行号，行政单位与所在目录一致。
- 每区工作簿含「机构信息」「异常机构」两表，异常行原因非空；城市总表行数 = 各区工作簿行数之和，不含异常机构表。
- 最终 Excel 不含明确外市地址段，可打开且表与列符合约定。

最终回复只说明：标准城市名、行政单位总数及来源状态计数、机构类别覆盖情况、最终地址行数和最终文件绝对路径；不展开逐来源检索过程。
