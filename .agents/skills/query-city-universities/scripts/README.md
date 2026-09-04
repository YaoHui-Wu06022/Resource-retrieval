# scripts 处理脚本

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `university_filter.py` | 按城市筛选普通高校，归类院校标签与办学性质。 |
| `university_domain.py` | 域名阶段 CLI：`probe` 探测现用性（公共 `web.probe_domains`），`merge` 汇总批次输出 `official_domain_manifest.json`。 |
| `university_page_fetch.py` | 单校页面抓取策略与校区/地址语义提取。 |
| `university_fetch_runner.py` | 按域名清单分片并发抓取，产出逐校结果与报告。 |
| `university_results_merge.py` | 合并逐校结果并校验文件名、覆盖与页面预算。 |
| `build_university_address.py` | 页面结果 → 候选地点地址对 → 清洗/校验/去重 → 地址记录。 |
| `build_excel.py` | 生成高校信息与异常校工作簿。 |
| `university_campus_rules.py` | 高校领域统一规则：校区语义、噪音/房间码、配对置信度与同址键。 |

## 修改记录

### 2026-09-03

- 脚本命名统一为 `university_` 前缀 + 动作后缀（filter / domain /
  page_fetch / fetch_runner / results_merge）；域名探测与批次汇总融合为
  `university_domain.py` 的 `probe` / `merge` 子命令。测试与 import
  同步改名，行为不变。
- 同校区“广州市广州大学城…”/“广东省广州市大学城…”等书写变体由公共
  `address_equivalence_key` 在生成阶段合并，不再产生误告警。
- 新增 `university_campus_rules.py`：集中校区层次折叠、办公/房间码噪音、
  多校区枚举标记、页源类型与异地城市校区判定等高校领域规则。
- `university_page_fetch.py` 待抓队列改为「同城校区详情 > 联系/概况/章程 >
  外市校区」优先级；每校 ≤6 页上限不变，预算耗尽时由
  `fetch_school_pages_with_coverage` 汇总漏抓同城校区并写入运行摘要。
- 章程/列表页出现多校区枚举句式时不再用 dom_context 猜测校区配对。
- `university_fetch_runner.py` 把 target_city 传入切片，并把
  `campus_coverage` 并入 `fetch_report` 条目。
- `build_university_address.py` 记录生成阶段做校区名规范（父校区子校园折叠，
  保留 `campus_name_raw`）、地址文本清洗（学校名尾缀/房间码）与中文数字
  门牌同址等价；单校区「校本部/无名校区」在最终去重中合并；同校区多个
  地址时优先保留地图可确证（consistent/partial/poi_match）的一条。
- 地址记录携带来源页类型、association 方法与置信度，供下游复核。

### 2026-09-03（v2.1 加固）

- `university_campus_rules.py` 新增费用行噪音、整串机构名与门牌号后机构名
  尾巴规则；`university_page_fetch.py` / `build_university_address.py`
  统一丢弃费用行与纯机构名候选，地址清洗阶段截断门牌后的院校名。
- `university_page_fetch.py` 校区链接只识别导航式校区链接（短文本 + 校区/校园
  或路径含校区/校园/campus 等段），新闻标题即使含“校区”也不再被当作校区
  详情页；纯“校园”后缀的网站栏目（美丽校园/南医校园等）只有路径带校区
  标记时才判为校区链接；校区详情页不再扩展校区子链接，避免子站导航吃满
  6 页预算。
- `campus_coverage` 告警语义收紧：`missing_campus_names` 只表示“详情页未抓
  且任何已抓页面都没有该校区地址”的真实缺口；详情页未抓但地址已由其他页面
  采到时写入信息字段 `detail_page_not_fetched`。

### 2026-09-03（v2.2 加固）

- 抓取策略不再“首页命中地址即早停”：首页后队列里仍有校区详情、学校概况/
  章程/地址/联系方式等白名单链接时继续补抓，直到 ≤6 页或队列耗尽；概况/
  联系链接只跟随整段学校级标题（学校概况/简介/章程/地址/联系我们等），
  `原XX简介`、产业学院简介、队伍概况等栏目不再被跟随。
- 校区扩展信号新增“单页 ≥2 个不同物理地址”（覆盖广美/广东交通首页多址
  无校区名场景）；自动发现的同 host+path 链接按路径去重，同终址变体不再
  重复抓取并占用页数预算。
- `university_campus_rules.py` 新增方向+距离（“东行4千米”）与校区职责/
  面积叙述句（“主要承担…教育任务”）噪音拒绝；`physical_location_key` 与
  新增 `road_name`/`has_house_number` 共用同一道路段提取实现。
- `university_page_fetch.py` 校区详情链接识别扩展到“标题短校区名 + 长预览
  描述且含位于/通讯地址”的列表页锚点（广药学校校区页详情链接可入队）；
  采集器支持“东校区地址是…”标签句（公共 `fetch_official_page`）。
- `build_university_address.py` 最终去重改为：无校区名学校的多个不同物理
  地址全部保留为独立行（不再每组择优丢行），同路已有门牌的无门牌变体丢弃；
  有校区名学校仍按“校本部/无名校区”合并规则与同址择优执行。
- 地址原文的“学校名+校区名位于…”句式和“通讯地址：”标签（公共采集器
  支持标点边界后的标签识别）可关联到对应校区。

### 2026-09-04（防残留加固）

- `university_campus_rules.py`：`clean_address_text` 新增联系词尾巴清洗
  （TEL/电话/传真/EMAIL/邮箱/邮编/QQ/微信，兼容带/不带冒号与号码）；
  新增 `has_contact_label_noise` 残留检测。
- `university_page_fetch.py`：`GENERIC_CAMPUS_PATTERN` 并入走进校园/校区分布/
  校园分布/学校导游/办学地点等栏目词，标题与链接不再把它们当校区名。
- `build_university_address.py`：`WEBSITE_MODULE_CAMPUS_NAMES` 同步并入上述
  栏目词；同路去重放宽为不限校区名，同校同路已有门牌时无门牌行一律丢弃；
  单字符退化路名（“路/街/道”）不参与同路判定，避免中文数字路名误删校区。
- `build_excel.py`：新增发布前质量门禁 `find_output_row_issues`，残留联系词
  与同路重复行命中即报错，需 Agent 修正来源后重跑。
