---
name: query-city-universities
description: "根据中国城市筛选教育部普通高校名单，检索学校官网中的校区地址，经公共地址组件规范化和地图验证后生成高校信息 Excel。"
---

## 目标

输入一个中国城市名称，生成该城市高校及校区的最终地址工作簿。

学校官网是地址事实来源。地图只用于交叉验证，或在官网未取得地址但已有明确地点名称时兜底；不得用地图内容改写官网原始地址。

## 运行前确认

- 先询问用户使用哪个 Python 环境或解释器，得到确认后再运行脚本；不得自行指定环境。
- 所有脚本使用同一环境。所需依赖为 `openpyxl`、`playwright` 及 Playwright Chromium。
- 公共地址阶段从进程环境或工作区 `.env` 读取 `AMAP_KEY`。
- 高校名单固定使用本 Skill `assets/` 中的教育部名单、985 名单和 211 名单。
- 缺少依赖、Chromium、`AMAP_KEY` 或资产文件时，停止并说明缺项；不要自行安装，也不要把未完成地图处理的结果当作完整结果。

## 执行边界

固定处理必须直接运行现有脚本，不得由 Agent 手工重算，也不得另写临时脚本复制其逻辑：

| 阶段 | 脚本 |
| --- | --- |
| 高校基础信息 | `scripts/prepare_universities.py` |
| 单个官网页面抓取 | `scripts/fetch_official_universities.py` |
| 页面批次组装、校验与公共地址输入 | `scripts/build_university_address_records.py` |
| 地址规范化、地图验证与兜底 | 工作区 `.dsh/components/process_addresses.py` |
| 最终工作簿 | `scripts/build_excel.py` |

下列工作必须由 Agent 根据当前证据判断，不得编码进临时 Python、PowerShell 或批处理脚本：

- 搜索和确认学校官网；
- 判断学校是否合并或停止独立办学；
- 审查每次页面抓取结果；
- 决定停止抓取或选择下一页。

官网抓取必须保持 Agent 在环：一次工具或终端调用最多执行一次 `fetch_official_universities.py`，只处理一所学校的一个页面。完整结果返回后，Agent 必须先审查，再决定是否发起下一次调用。允许原样保存单次 JSON；禁止循环抓取多校或多页、自动选页、自动停止及自动生成停止原因。

## 1. 生成基础信息

运行 `scripts/prepare_universities.py`，输入参数：

- `--city`：用户提供的城市名称。

读取脚本最终输出中的 `city`、`date`、`school_count` 和 `output_dir`。后续全部文件写入 `output_dir`。

脚本生成：

- `base_information.json`：后续处理输入；
- `base_information.xlsx`：保留教育部原始序号，供人工检查。

后续逐校处理 `base_information.json` 的 `schools`。每个学校对象必须原样保留以下字段：

| 字段 | 含义 |
| --- | --- |
| `source_sequence` | 教育部源表序号 |
| `school_name` | 学校名称 |
| `school_identifier` | 学校标识码 |
| `supervising_authority` | 主管部门 |
| `location_city` | 标准城市名 |
| `education_level` | 办学层次 |
| `source_remark` | 原始备注，仅内部保留 |
| `school_tag` | 985、211 或空值 |
| `school_nature` | 公办、民办或待核验 |

## 2. 搜索官网并逐页提取

### 官网搜索与身份确认

每所学校只使用一次 Agent 自有 Web Search，查询学校全名及官网。可比较同次搜索返回的多个候选，不得为更换域名再次搜索。

Agent 按以下规则确认官网：

- 页面标题、站点名称或正文明确对应学校全名；
- 优先选择可访问的学校主站，`.edu.cn` 不是硬性条件；
- `.edu.cn` 主站不可访问时，可采用同次搜索结果中归属明确的 `.cn` 主站；
- 招生平台、百科、媒体、自媒体、地图页面和第三方院校库均不是学校官网；
- 页面跳转到新域名时，必须用同次搜索证据重新确认新域名归属。

若同次搜索已明确证明学校合并或停止独立办学，将该校标记为 `skipped`，不抓取页面，也不进入地图服务。该判断只能由 Agent 作出。

### 单页抓取契约

运行 `scripts/fetch_official_universities.py`，输入参数：

- 位置参数：当前页面 URL；
- `--official-domain`：已确认官网域名的主机名，可重复传入；不得传完整 URL。

脚本每次输出一个完整页面对象。

Agent 必须审查：`final_url`、`address_candidates`、`campus_hints`、`related_links` 和 `warnings`。

页面对象及候选字段必须原样保存，不得由模型重建或删改。

### 逐页决策

1. 先抓取官网首页。
2. 信息不足时，只能从当前结果的同域 `related_links` 选择下一页，优先级为：联系方式或地址页、明确校区页、学校概况页。
3. 每所学校最多抓取三页，失败调用也计入预算；第二页和第三页必须在 Agent 审查上一页后分别决定。
4. 满足任一条件时停止：
   - 已取得明确地址，且没有未解决的 `campus_hints` 或指向其他校区的高价值链接；
   - 三页预算用尽；
   - 剩余链接均非同域或与地址、校区无关。
5. `final_url` 为空或 `warnings` 表明访问失败时，不得声称已取得地址；保留失败页并计入预算。没有可继续链接时，只能以无可用链接停止。

不得根据区县、道路或常识反推校区名。只有页面明确给出校区名时，地点名称才使用“学校名称 + 校区名称”；校区名未知时只使用学校名称，不补“校本部”。无标签页脚地址可不强行提取，交由已有地点名称触发地图兜底。

## 3. 记录逐校检索结果

在 `output_dir` 创建 `university_retrieval_results.json`，顶层只包含 `items`。每所基础名单学校必须出现一次：

- 正常处理：记录 `school_identifier`、`processing_status = completed` 和 `pages`；`pages` 按访问顺序保存一至三个单页脚本原始输出。
- 合并或停止独立办学：记录 `school_identifier`、`processing_status = skipped`、`skip_reason` 和 HTTP(S) `skip_reference`，不填写 `pages`。

`skip_reason` 只能是 `merged` 或 `ceased_independent_operation`。访问失败但未确认合并或停止独立办学的学校仍为 `completed`，并保留失败页面结果。

不要填写城市、学校名称、完整学校对象、`schema_version` 或 `stage`；这些固定内容由下一步脚本从 `base_information.json` 补齐。

## 4. 执行固定输出链路

依次运行以下脚本，不得手工修改任何中间输出：

### 4.1 生成公共地址输入

运行 `scripts/build_university_address_records.py`：

- 输入：`--input university_retrieval_results.json`
- 输出：自动归档 `university_page_results.json`，并按 `--output address_records.json` 生成公共地址输入
- 固定值：`source_nature = web_search`
- 校验：页面归档覆盖基础名单且学校对象来自基础信息；`base_school_count = completed_school_count + skipped_school_count`，且 `missing_school_count = 0`

### 4.2 处理地址

运行工作区 `.dsh/components/process_addresses.py`：

- 输入：`--input address_records.json`
- 输出：`--output processed_address_records.json`
- 校验：不得存在未处理的地图错误；预期调用地图时，`map_request_count` 不得为 `0`

最终地址按以下规则确定：

- 官网规范地址完整：采用规范地址；
- 官网没有地址，且地图唯一兜底成功：采用地图地址；
- 地址指向目标城市外、规范化冲突或没有合格兜底结果：最终地址留空。

### 4.3 生成最终工作簿

运行 `scripts/build_excel.py`：

- 输入：`--input processed_address_records.json`
- 输出：`--output 高校建筑查询_<标准城市名>_<YYYY-MM-DD>.xlsx`
- 校验：文件可以打开，仅包含一张“高校信息”表，且每行最终地址非空

工作簿只输出 `final_address` 非空的地点，列顺序固定为：

| 顺序 | Excel 列 | 数据来源 |
| ---: | --- | --- |
| 1 | 序号 | 按城市结果重新编号 |
| 2 | 学校名称 | `place_name` |
| 3 | 主管部门 | `attributes.supervising_authority` |
| 4 | 办学层次 | `attributes.education_level` |
| 5 | 院校标签 | `attributes.school_tag` |
| 6 | 办学性质 | `attributes.school_nature` |
| 7 | 最终地址 | `final_address` |
| 8 | 地址获取方式 | `map_status == fallback` 时为“地图兜底”，否则为“官网提取” |
| 9 | 信息来源 | `source_reference` |

不另设校区列，不展示学校标识码和所在地，不生成异常信息工作表。

## 不可变规则

- 每所学校最多一次 Web Search、最多三次官网页面抓取；不得用额外搜索弥补页面预算耗尽。
- 只有已确认的学校官网页面可以提供原始地址和校区名称。
- 官网有规范地址时，地图只做交叉验证；即使地图冲突，最终地址仍按公共规则采用官网规范地址并保留内部原因。
- 官网没有地址时，只有已取得 `place_name` 才允许地图兜底。
- 不输出最终地址为空的记录。

## 完成检查

- 全部文件位于 `output_dir`。
- 脚本生成的页面批次归档覆盖基础名单，无重复、遗漏或未分类学校。
- `completed` 每校最多三页且均为单页脚本原始输出；`skipped` 均有合法原因和证据链接。
- 所有继续或停止决定均由 Agent 在逐页审查后作出，任务目录内没有批量抓取、自动选页或自动停止脚本。
- 聚合完整性指标通过，公共地址结果没有未处理的地图调用错误。
- 最终工作簿结构和列顺序正确，每行最终地址非空。

最终回复只说明标准城市名、基础名单学校数、公共处理状态计数、最终地址行数和最终文件绝对路径，不展开逐校搜索过程。
