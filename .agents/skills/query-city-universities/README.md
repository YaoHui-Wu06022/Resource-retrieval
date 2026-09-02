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
| `scripts/fetch_official_universities.py` | 固定策略批量抓取（`--school-batch`）与校区语义提取；`--session` 仅保留作调试入口。 |
| `scripts/run_university_fetch.py` | 按 `official_domain_manifest.json` 分片并发抓取，自动落盘单校结果并产出 `fetch_report.json`/`retry_failures.json`。 |
| `scripts/merge_domain_batches.py` | 汇总域名确认批次 `domain_batches/*.json`，校验覆盖后输出 `official_domain_manifest.json`。 |
| `scripts/merge_university_results.py` | 合并逐校结果并校验文件名、学校覆盖、处理状态与页面预算。 |
| `scripts/build_university_address.py` | 页面结果 → 公共地址记录（候选去重、校区回填、同址冲突告警），并包含地图同址去重（优先保留校区名）。 |
| `scripts/build_excel.py` | 生成最终工作簿：「高校信息」表（固定十一列）与「异常校」表（固定八列，列出最终地址为空的学校及异常原因）。 |

## 修改记录

### 2026-09-02

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
