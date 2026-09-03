---
name: query-city-medical-institutions
description: "按中国城市检索政府公开的持证/备案医疗机构（医院、诊所、门诊部、社康中心、医学实验室等），整理名称、类型、级别和地址并生成 Excel。"
---

## 输入与运行条件

输入：一个中国城市。输出：该城市持证/备案医疗机构的地址信息工作簿
（「机构信息」+「异常机构」工作表）。

- 环境未确认先询问；确认后全程使用同一环境。依赖：`openpyxl`，
  `query-city-core` 已安装；在线查询页需浏览器采集时另备 Playwright。
- 本 Skill 主要使用政府官方地址，默认不依赖高德补充查询；只有需要对
  空地址/异常地址做地图兜底时才从环境变量或 `.env` 读取 `AMAP_KEY`。
- 缺依赖、浏览器或公共组件时停下说明缺项；不自装、不另写临时脚本
  复制固定逻辑。
- 执行约定：命令示例的相对路径相对 skill 根目录；非交互 Python 命令
  按仓库 AGENTS.md 的运行约定执行。

全部输出写入
`output/<标准城市名>/<YYYY-MM-DD>/Medical_Institutions/<HHMMSS>/`。
每次调用用新 `<HHMMSS>`，重新检索并生成全部结果，不覆盖旧运行目录。

## 执行边界与 Agent 分工

固定处理统一调用下表脚本，不另写临时脚本拆分、转换或组装来源输出：

| 用途 | 命令 |
| --- | --- |
| 标准化城市、取下级行政区 | `python -m query_city_core.address.city` |
| 检索并保存官方来源 | Agent 检索政府网站，来源文件存入 `sources/` |
| 检查来源、生成提取计划 | `scripts/medical_government_flow.py inspect` |
| 生成公共地址输入 | `scripts/medical_government_flow.py extract` |
| 规范化地址与可选地图兜底 | `python -m query_city_core.address.process` |
| 生成最终工作簿 | `scripts/build_excel.py` |

- Agent 负责来源检索、机构类别覆盖核对、来源清单质量判断与人工复核；
  固定脚本负责按官方字段解析、地址拆分、去重、排序与工作簿格式。
- `government_source.json` 与 `sources/` 下的原始文件只能由 Agent 在
  人工确认后写入；解析脚本只读取，不回写来源结论。

## 1. 取得运行目录与城市上下文

```powershell
$runDate = Get-Date -Format yyyy-MM-dd
$runTime = Get-Date -Format HHmmss
$runDir = 'output/<标准城市名>/' + $runDate + '/Medical_Institutions/' + $runTime
New-Item -ItemType Directory -Force "$runDir\sources" | Out-Null
python -m query_city_core.address.city --city <用户城市> > "$runDir/city_context.json"
```

`<标准城市名>` 用城市组件返回的规范名称。后续中间文件全部写入
`$runDir`。

## 2. 检索并保存官方来源

**检索规则（Agent 判断）**

- 只采用政府卫健委/区政府发布的持证、登记或备案名单；正文或附件中
  必须实际含医疗机构记录。禁用地图、百科、媒体、第三方机构库。
- 机构类别覆盖医院、诊所、门诊部、社区卫生服务中心/站、村卫生室、
  医学检验实验室等；每类都要有官方来源或明确“无公开名单”结论。
- 按「卫生健康委/中医药局 → 区政府门户与区卫健局 → 上级政府数据平台」
  的顺序检索；存在多个数据批次时只取“数据截至日期”最新的一期。
- 访问失败不等于无来源；在线查询页无法直接下载时用浏览器采集证据，
  禁止凭空补记录或把“没搜到”写成 `no_official_source`。

**写来源清单**

- 将确认可用的来源文件保存到 `$runDir/sources/`；
- 把来源写入 `$runDir/government_source.json`，字段见
  [来源格式](references/medical-source-format.md)；
- `status` 只允许 `ready` / `missing` / `no_official_source`；
  `ready` 来源必须已有本地文件。

## 3. 检查并复核提取计划

- 输入：`government_source.json`、`city_context.json`
- 命令：`scripts/medical_government_flow.py inspect --sources <government_source.json> --output <extraction_plan.json>`
- 输出：`extraction_plan.json`

Agent 复核规则列、表头映射与对象列表字段；正确规则设 `approved = true`，
来源设 `review_status = ready`。

## 4. 生成公共地址输入

- 输入：已复核的 `extraction_plan.json`
- 命令：`scripts/medical_government_flow.py extract --plan <extraction_plan.json> --output <address_records.json>`
- 输出：`address_records.json`

公共引擎按官方字段保留机构名称、类型、级别，按执业地点拆分地址，剔除
明确指向外市的地址段；无地址记录继续保留在结果中供异常表使用。

## 5. 处理地址

- 输入：`address_records.json`
- 命令：`python -m query_city_core.address.process --input <address_records.json> --output <processed_address_records.json>`
- 输出：`processed_address_records.json`

官方完整地址直接采用；规范化冲突但官方地址仍可用的记录由 Excel 阶段
保留官方地址。最终工作簿展示不依赖地图查询结果。

## 6. 生成最终工作簿

- 输入：`processed_address_records.json`、`anomaly_records.json`
- 命令：`scripts/build_excel.py --input <processed_address_records.json> --anomalies <anomaly_records.json> --output <医疗机构信息_<标准城市名>_<YYYY-MM-DD>.xlsx>`
- 输出：每个行政单位一份区级工作簿 + 一份城市总表

「机构信息」表列：序号、行政单位、机构名称、机构类型、机构级别、
查询日期、地址、地址获取方式、地图匹配状态、信息来源。「异常机构」
表列：序号、行政单位、机构名称、机构类型、机构级别、异常原因、
信息来源、查询日期。类型和级别保留官方原文，来源没有时留空，不归一化、
不按名称推断。

## 完成检查

- `government_source.json` 标明每类机构来源与覆盖缺口，`ready` 来源均有
  本地文件。
- 每条输出记录可追溯到原始来源文件/页面与行号。
- 最终 Excel 不含明确外市地址段；城市总表行数 = 各区工作簿行数之和。
- 每个区级工作簿含「机构信息」「异常机构」两个工作表，异常行原因非空。
- 最终工作簿可打开，表与列符合约定。

最终回复只说明：标准城市名、来源状态计数、机构类别覆盖情况、最终
地址行数和最终文件绝对路径；不展开逐来源检索过程。
