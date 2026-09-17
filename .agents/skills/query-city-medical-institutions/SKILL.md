---
name: query-city-medical-institutions
description: "按中国城市的直接下级行政单位检索政府公开的持证/备案医疗机构（医院、诊所、门诊部、社康中心、医学实验室等），整理名称、类型、级别和地址并生成区级和城市汇总 Excel。"
---

## 输入与运行条件

输入城市 → 输出各直接下级行政单位持证/备案医疗机构地址工作簿（每区「机构信息」+「异常机构」+ 城市总表）。

- 环境未确认先询问；确认后全程使用同一环境。依赖 `openpyxl`、`query-city-core`；在线查询页需浏览器采集时另备 Playwright。
- 默认用政府官方地址，不依赖高德；仅空/异常地址做地图兜底时从 `.env` 或环境读 `AMAP_KEY`。
- 缺依赖、浏览器或公共组件即停下说明；不自装、不另写临时脚本复制固定逻辑。
- 输出到 `output/<标准城市名>/<YYYY-MM-DD>/Medical_Institutions/<HHMMSS>/`，每次新目录，不覆盖旧结果。

## 流程与分工

| 步骤 | 命令/方式 |
| --- | --- |
| 行政单位 | `python -m query_city_core.address.city` |
| 来源保存 | `scripts/medical_government_flow.py` 的 `list-links`/`download`/`collect-details`（按需，见 §2） |
| 平台分页抓取 | `scripts/medical_government_flow.py platform-query --manifest <government_source.json>` |
| 提取计划 | `scripts/medical_government_flow.py inspect`（见 §3） |
| 记录提取 | `scripts/medical_government_flow.py extract`（见 §4） |
| 地址规范化 | `python -m query_city_core.address.process` （串行） |
| 工作簿 | `scripts/build_excel.py`（见 §6） |
| 质量闸门 | `scripts/medical_quality_check.py --input-dir <运行目录>` |

来源检索、类别覆盖与来源质量、计划复核由 Agent 依官方证据完成；字段解析、地址拆分、去重、排序与工作簿格式由脚本完成。`government_source.json` 与 `sources/` 原始文件只能由 Agent 确认后写入。

## 1. 行政单位

```powershell
$runDate = Get-Date -Format yyyy-MM-dd; $runTime = Get-Date -Format HHmmss
$runDir = "output/<标准城市名>/$runDate/Medical_Institutions/$runTime"; New-Item -ItemType Directory -Force $runDir | Out-Null
python -m query_city_core.address.city --city <用户城市> > "$runDir/city_context.json"
```

按 `subdivisions[].name` 建同名目录并依次处理；不增删/合并/改名，不查更低一级。

## 2. 逐区检索并保存官方来源

**规则**

- 只采用政府卫健委/区政府发布的持证、登记或备案名单，正文或附件须实际含机构记录；禁用地图、百科、媒体与第三方库。
- 类别须覆盖医院、诊所、门诊部、社区卫生服务中心/站、村卫生室、医学检验实验室等；每类有官方来源或明确“无公开名单”结论。
- 结果按区交付、来源先市后区。层级：市级统一注册查询平台/市级发证全量 → 区级全量名单 → 省级发证名单 → 个案备案公示。市平台须可按区过滤/枚举或每行带所在区；区级名单补充校正；省级补充省发证机构；个案公示只作证据不作全量；统一搜索平台只用于定位页面。
- `query_platform` 合格条件：政府卫生部门运营；可按行政区过滤并分页（或返回带区的整市记录）；返回含执业地址的官方字段；有“数据截至”或更新说明。`platform-query` 保存每页原始响应并生成汇总记录；平台“区发证以各区卫健局为准”等口径记入来源项并在最终说明体现，不否定其证据资格。
- 一登记多执业地址：行拆分后先做城市级跨目录去重，再按最终物理地址分桶；复核“所在区/行政区划”列映射，不得把登记区当物理区剔除记录。
- 访问失败 ≠ 无来源；在线查询页不可直接下载时用浏览器采证；确无全量名单才写 `no_official_source`，禁止凭空补记录或以“没搜到”当结论。

**保存**

- 栏目/附件/详情页用 `list-links/download/collect-details`，文件放 `<行政单位目录>/sources/`。
- `query_platform` 先以 `status=pending` 写入，再执行 `platform-query --manifest <government_source.json>`：成功回写 `ready`+`local_file`+`platform_result`（平台总数、页数、原始页清单），失败回写 `missing`+原因。
- 写入 `<行政单位目录>/government_source.json`（字段见 [来源格式](references/medical-source-format.md)）；顶层含完整 `city_context` 与 `administrative_unit`（原样取 `subdivisions` 一项）；`status` 限 `pending/ready/missing/no_official_source`，`ready` 必须有本地文件。

## 3. 复核提取计划

`inspect --sources <government_source.json> --output <extraction_plan.json>`，每区目录单独执行；复核列、表头映射与对象列表字段，正确规则 `approved=true`、来源 `review_status=ready`。

## 4. 提取记录

`extract --plan <extraction_plan.json> --output <address_records.json>`；仅当 `stage=address_records` 且 `error_count=0` 才继续。按官方字段保留名称/类型/级别，按执业地点拆分地址并剔除明确外市段；保留来源行行政区字段既有过滤，跨区多址段不因目录剔除（工作簿按物理地址分桶）；无地址记录保留供异常表。

## 5. 处理地址

`address.process` 串行（同一时间一个进程）。官方完整地址直接采用；规范化冲突但官方地址仍可用时由 Excel 阶段保留官方地址；最终工作簿不依赖地图结果。

## 6. 生成工作簿

运行 `scripts/build_excel.py --input-dir <运行目录> --output <医疗机构信息_<标准城市名>_<YYYY-MM-DD>.xlsx>`：先城市级跨目录去重（登记号+地址，其次机构名+行政单位+地址），再按最终物理地址（无最终地址用官方原文地址）分桶：每区一份区级工作簿 + 运行目录一份城市总表。区级含「机构信息」「异常机构」；总表为“机构信息”汇总 + 各区工作表，不含异常机构表；无地址异常行保留在来源单位目录异常表。

- 「机构信息」列：序号、行政单位、机构名称、机构类型、机构级别、查询日期、地址、地址获取方式、地图匹配状态、信息来源。
- 「异常机构」列：序号、行政单位、机构名称、机构类型、机构级别、异常原因、信息来源、查询日期。异常行由脚本从 processed 结果推导（最终地址空且无官方原文，或带 `abnormal_reason`），不另设异常清单文件。
- 类型/级别保留官方原文，缺失留空；级别为“未定级/无定级/无级别”时该列显示为空。

## 完成检查

- 每区有来源清单与合法 `address_records.json`/`processed_address_records.json`；`ready` 均有本地文件；记录可追溯到来源文件/页面与行号，行政单位与目录一致。
- 每区工作簿双表且异常原因非空；城市总表行数 = 各区之和，不含异常机构表；Excel 不含明确外市地址段、可打开。
- 交付前运行 `medical_quality_check.py` 且 `passed=true`：有 ready `query_platform` 的区，主表行数 ≥ 平台当区总数 × 90%；平台某大类达阈值而交付为零时须有对应 `no_official_source` 理由；无任何 ready 全量来源的区判定未完成。

最终回复只给：标准城市名、行政单位总数及来源状态计数、机构类别覆盖情况、平台数据截至与口径说明、最终地址行数、最终文件绝对路径；不展开逐来源过程。
