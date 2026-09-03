# query-city-universities 高校检索 Skill

## 本层职责

根据中国城市筛选教育部普通高校名单，确认官网域名清单后，
由脚本多进程并发抓取官网并提取校区地址，经公共地址组件规范化和地图验证后
生成高校信息 Excel。固定处理统一调用 `scripts/` 下的脚本，
不另写临时脚本复制逻辑。

## 目录结构

- `assets/`：教育部普通高校名单、985/211 名单（固定资产）。
- `references/`：单校结果文件规范等参考文档。
- `scripts/`：固定处理脚本。
- `scripts/tests/`：脚本测试。

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `SKILL.md` | 执行规范：城市名录生成、逐校官网检索、合并、地址处理与工作簿生成的完整流程与边界。 |
| `requirements.txt` | 运行依赖。 |
| `assets/全国普通高等学校名单.xlsx` | 教育部普通高校名单，按城市筛选学校。 |
| `assets/985_universities.xlsx`、`211_universities.xlsx` | 本科院校标签名单。 |
| `references/retrieval-result-format.md` | `school_results/<学校标识码>.json` 单校结果文件字段规范。 |
| `scripts/filter_universities.py` | 按城市筛选普通高校，归类院校标签与办学性质，输出 `city_universities.json/xlsx`。 |
| `scripts/fetch_official_universities.py` | 固定策略批量抓取（`--school-batch`）与校区语义提取；先抓首页并按候选页/多校区线索扩展补抓，首页做身份校验；`--session` 仅保留作调试入口。 |
| `scripts/run_university_fetch.py` | 按 `official_domain_manifest.json` 分片并发抓取，自动落盘单校结果并产出 `fetch_report.json`/`retry_failures.json`。 |
| `scripts/merge_domain_batches.py` | 汇总域名确认批次 `domain_batches/*.json`，校验覆盖后输出 `official_domain_manifest.json`。 |
| `scripts/probe_official_domains.py` | 探测普通项主页可达性与跳转终域，输出 `domain_probe_report.json`，供域名批次复核现用域名。 |
| `scripts/merge_university_results.py` | 合并逐校结果并校验文件名、学校覆盖、处理状态与页面预算。 |
| `scripts/build_university_address.py` | 页面结果 → 公共地址记录（候选去重、校区回填、同址冲突告警），并包含地图同址去重（优先保留校区名）。 |
| `scripts/build_excel.py` | 生成最终工作簿：「高校信息」表（固定十一列）与「异常校」表（固定八列，列出最终地址为空的学校及异常原因）。 |

## 修改记录

### 2026-09-02

- `scripts/probe_official_domains.py`
  - 探测逻辑下沉 `query_city_core/web/probe_domains.py`，命令层只保留
    高校批次读取与字段适配；报告条目改用中立的 `place_id`/`place_name`。
- `scripts/fetch_official_universities.py`
  - 过滤“上一条/下一条/上一篇/下一篇/上一页/下一页/返回列表”等翻页
    导航链接，避免详情页底部导航被当作校区线索或后续抓取目标。
- `scripts/build_university_address.py`
  - 兼容旧抓取结果：页面 `related_links` 中的翻页导航校区名不再生成
    无地址记录；`广州校区校园` 一类冗余后缀折叠为 `广州校区`，
    有地址时不再额外产生空地址校区行。
- `scripts/tests/`
  - 新增翻页导航不生成校区提示/空地址记录、冗余校区后缀别名用例。
- `scripts/build_university_address.py`
  - 生成公共地址记录前逐校清洗：丢弃外市校区记录、无校区标签的办公点/
    报名点噪音地址；同址校区写法合并并优先保留主页来源名称；
    重复空地址校区提示只保留一条。命令与输出格式不变。
- `SKILL.md`
  - 域名确认阶段新增现用性探测步骤与 `domain_probe_report.json` 复核；
    跳转域名证据扩展为“同次搜索证据或官方探测的页面身份匹配证据”。
  - 页面策略改为校区覆盖优先：首页命中地址不再阻止抓取
    `candidate_urls`；多校区线索判定不再要求“尚无地址”；页数预算
    同步（默认 ≤3 页，需抓候选页或多校区线索时放宽到 ≤6 页）。
- `scripts/probe_official_domains.py`
  - 新增域名现用性探测：读取 `domain_batches/*.json`，访问普通项主页，
    输出可达性、跳转终域、标题身份匹配与建议。
- `scripts/fetch_official_universities.py`
  - `has_campus_expansion_signal` 去掉“尚无地址”限制，页面显示 ≥2 个
    校区提示或校区链接即放宽预算；
  - 新增首页身份校验：标题不含学校名称时向页面结果写入 warning；
  - `fetch_school_pages` 改为先抓首页再抓完全部候选页（首页命中地址
    也继续），候选页抓完且无多校区线索才停止；
  - 预算容纳“首页 + 候选页”，上限与多校区扩展一致为 6 页。
- `scripts/run_university_fetch.py`
  - 域名清单处理项携带 `school_name`（供身份校验）；
  - `fetch_report.json` 每校新增 `identity_warning` 标记。
- `scripts/tests/`
  - 新增 `test_probe_official_domains.py`；
  - 同步抓取策略用例（候选页抓取、带地址的多校区线索、身份校验）。

- `SKILL.md`
- 域名确认不再使用子 Agent：改为按批 WebSearch、写回
    `domain_batches/*.json` 并汇总，删除子 Agent 并行确认相关描述。
- `SKILL.md`
  - 表述收缩：按基础教育风格重写，保留输入输出、命令、文件格式与边界，
    删除原理性长段说明。
- `SKILL.md`
  - 输出目录层级统一为
    `output/<标准城市名>/<YYYY-MM-DD>/Higher_Education/<HHMMSS>/`，
    与基础教育的 `<YYYY-MM-DD>/Basic_Education/<HHMMSS>/` 对齐。
- `SKILL.md`
- 域名确认按学校批次进行：按批 WebSearch 后原子写回
    `domain_batches/*.json`，再用 `merge_domain_batches.py` 汇总校验并复检
    `failure_reason` 项；
- `scripts/merge_domain_batches.py`
  - 新增域名批次汇总脚本：校验批次与城市名录一一对应、拒绝含
    `failure_reason` 的输出，按城市名录顺序生成 `official_domain_manifest.json`。
- `SKILL.md`
  - 官网抓取改为「确认域名清单 + `run_university_fetch.py` 多进程
    固定策略抓取」，删除子 Agent 逐页交互抓取与共享会话约束；
  - 新增无官网出口 `no_official_site`，无官网学校可带证据进入地址处理与「异常校」。
- `scripts/fetch_official_universities.py`
  - 新增 `--school-batch` 固定策略批量模式：先抓 `home_url`，有地址即停，
    否则补抓 `candidate_urls`/同域相关链接，每校默认最多 3 页，
    完整页面对象由脚本原子写入 `school_results/<标识码>.json`。
  - 多校区自动扩展：页面出现 ≥ 2 个校区提示或校区链接且尚无地址时，预算自动放宽到 6 页，同一校区详情只补抓一次。
- `scripts/run_university_fetch.py`
  - 新增并发运行器：校验 `official_domain_manifest.json` 覆盖、分片多进程抓取、
    直接写出 `no_official_site`/`skipped` 结果、生成 `fetch_report.json` 与
    `retry_failures.json`，支持 `--only-failures` 统一复检。
- `scripts/build_university_address.py`
  - 接受 `no_official_site` 状态，为无官网学校生成带 `abnormal_reason` 的空地址记录。
- `scripts/build_excel.py`
  - 「异常校」原因优先取 `attributes.abnormal_reason`。
- `references/retrieval-result-format.md`
  - 新增 `no_official_site` 单校结果格式。
- `scripts/tests/`
  - 新增固定策略批量抓取、`run_university_fetch.py` 运行器与
    `no_official_site` 出口用例，以及域名批次汇总用例。
- `SKILL.md`
  - session 交互格式增加 `school_identifier`，同一学校的多页在同一浏览器
    context 内复用 page，学校切换时新建；最终列顺序与实现对齐
    （发布日期在地址列之前）；
  - 输出路径与运行目录增加 `<HHMMSS>` 时间戳层，
    同天同城多次调用各自独立、不互相覆盖。
- `scripts/fetch_official_universities.py`
  - `run_session` 按 `school_identifier` 划分浏览器上下文；
  - `build_address_candidates` 拆分为 `expand_address_evidence` 与
    `build_address_candidate` 两个纯函数；
  - 删除 `--refresh-school-results-dir` 与单页 CLI 模式
    （`refresh_school_results`、`fetch_university_pages` 一并移除），
    命令行只保留 `--session`。
- `scripts/script_io.py`
  - 文件删除，JSON 读写改用公共层 `query_city_core.io_utils`。
- `scripts/filter_universities.py`
  - `schools` 记录不再携带 `source_remark`（备注仅用于筛选时归类办学性质）；
  - `city_universities.json` 输出改原子写；
  - `_load_workbook_for_reading` docstring 改中文，删除重复的 warnings 过滤；
  - `main` 以 `city_context.json` 所在目录为本次运行目录，
    删除日期推导的 `build_output_directory` 及相关常量。
- `scripts/build_university_address.py`
  - `CITY_UNIVERSITY_FIELDS` 移除 `source_remark`；
  - 同址键改用公共层 `query_city_core.address.common.address_detail_key`。
- `scripts/build_university_address_post.py`
  - 文件合并入 `build_university_address.py` 后删除，
    `postprocess_university_address_records` 与同址键逻辑统一使用公共 `address_detail_key`。
- `scripts/build_excel.py`
  - 查询日期校验改用公共 `DATE_CELL_PATTERN`；
  - 原子保存改用公共 `write_workbook_atomically`；
  - 删除未使用的 `copy` 导入；
  - 新增「异常校」工作表：从 `processed_address_records.json` 汇总
    最终地址为空的学校，列为 序号、学校名称、院校标签、办学性质、
    异常原因、地图匹配状态、信息来源、查询日期。
- `scripts/tests/`
  - 与上述改动同步：build_excel 列序断言、session context 复用用例、
    `source_remark` 夹具移除。
- `references/retrieval-result-format.md`
  - 表述收缩：正常/跳过/无官网三态的规则改为紧凑条目，字段约束并入
    各 JSON 示例后，删除重复句式，保留全部字段、页面预算与证据要求；
    汇总边界改为要点列表。
