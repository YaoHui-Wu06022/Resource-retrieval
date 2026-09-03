# query-city-universities 高校检索 Skill

## 本层职责

根据教育部普通高校名单筛选城市高校，确认官网域名并抓取页面，提取校区
地址，经公共地址处理与地图验证后生成高校信息 Excel。执行流程见
`SKILL.md`，遵循 web_search Skill 模板
（`doc/web-search-skill-template.md`）。

## 目录结构

- `assets/`：教育部普通高校名单、985/211 名单（固定资产）。
- `references/`：单校结果文件规范。
- `scripts/`：固定处理脚本（角色见 `scripts/README.md`）。
- `scripts/tests/`：脚本测试。
- `requirements.txt`：锁定共享运行库 `query-city-core==0.1.0`。

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `SKILL.md` | 执行规范：域名确认、抓取、合并、地址处理与工作簿生成。 |
| `AGENTS.md` | 本 Skill Python 代码操作规范。 |
| `references/retrieval-result-format.md` | `school_results/<标识码>.json` 单校结果规范。 |
| `scripts/university_filter.py` | 按城市筛选普通高校并输出 `city_universities.json/xlsx`。 |
| `scripts/university_domain.py` | 域名阶段 CLI：`probe` 探测主页现用性，`merge` 汇总批次输出 `official_domain_manifest.json`。 |
| `scripts/university_page_fetch.py` | 单校页面抓取策略与校区语义提取库。 |
| `scripts/university_fetch_runner.py` | 并发抓取运行器与 `fetch_report.json`/`retry_failures.json`。 |
| `scripts/university_results_merge.py` | 合并逐校结果并校验覆盖与页面预算。 |
| `scripts/build_university_address.py` | 页面结果 → 候选地点地址对 → 清洗/校验/去重 → 地址记录。 |
| `scripts/build_excel.py` | 生成高校信息与异常校工作簿。 |

## 修改记录

### 2026-09-03

- 脚本命名统一为 `university_` 前缀 + 动作后缀（filter / domain /
  page_fetch / fetch_runner / results_merge）；域名探测与批次汇总融合为
  `university_domain.py` 的 `probe` / `merge` 子命令。测试与 import
  同步改名，行为不变。
- 高校地址链路规则重整：新增 `scripts/university_campus_rules.py`；
  官网抓取按「同城校区优先」排队并产出 `campus_coverage` 覆盖告警；
  多校区枚举页不再猜测校区配对；记录生成阶段统一校区名并清洗学院页
  房间码地址；公共地址层新增 `needs_review` 地图状态，只有道路/门牌/
  锚点可确证时才用地图补全缺区官网地址。

### 2026-09-03（v2.2 加固）

- 抓取层不再首页命中地址即停：学校概况/章程/地址/联系方式等白名单链接
  继续补抓，校区扩展信号增加“单页 ≥2 个不同物理地址”；同 host+path
  链接按路径去重，校区预览长链接（标题 + 位于/通讯地址描述）也可入队。
- 构建层：无校区名多址全部保留为独立行，同路有门牌的无门牌变体丢弃；
  方向距离与校区职责叙述句在候选层拒绝。
- 提取层：公共采集器支持标点边界后的“通讯地址/地址/校址”与
  “X校区地址是…”标签；高校侧支持“学校名+校区名位于…”句式的校区名提取。
- 公共地址层：规范化完整但无道路/门牌且含具体地点文本的行先走 POI 严格
  匹配，未命中保留官网原文并标“部分匹配·待复核”；纯区级空文本保持留空。

### 2026-09-03（文档修订）

- SKILL.md 页面策略与 v2.2 行为对齐：首页命中地址后不再早停，白名单相关
  链接在预算内继续补抓；校区扩展信号补充“单页 ≥2 个不同物理地址”；
  自动发现链接按 host+path 去重。
- SKILL.md 与 `references/retrieval-result-format.md` 的工作簿列数与
  页数预算描述对齐实现（「异常校」九列）。
