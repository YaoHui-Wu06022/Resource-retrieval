---
name: query-city-universities
description: "根据中国城市筛选教育部普通高校名单，检索学校官网中的校区地址，经公共地址组件规范化和地图验证后生成高校信息 Excel。"
---

## 输入与运行条件

输入城市 → 输出该市高校及校区最终地址工作簿（「高校信息」+「异常校」）。

- 环境未确认先询问；确认后全程使用同一环境。
- 依赖：`openpyxl`、`playwright` 与 Playwright Chromium；高校名单固定用本 Skill `assets/` 的普通高校、985、211 名单。
- `AMAP_KEY` 从环境变量或 `.env` 读取。
- 缺依赖、密钥、浏览器或资产即停下说明；不自装、不另写临时脚本替代固定逻辑；未完成地图处理的结果不算完整结果。
- 输出到 `output/<标准城市名>/<YYYY-MM-DD>/Higher_Education/<HHMMSS>/`，每次新建 HHMMSS，不覆盖旧目录。

## 流程与分工

| 步骤 | 命令/方式 |
| --- | --- |
| 行政单位 | `python -m query_city_core.address.city` |
| 城市高校名录 | `scripts/university_filter.py` |
| 域名确认 | Agent 按批 WebSearch → `domain_batches/*.json` → 汇总 `official_domain_manifest.json` |
| 域名探测 | `scripts/university_domain.py probe/merge --run-dir <runDir>` |
| 并发抓取 | `scripts/university_fetch_runner.py`（参数见 §2.2） |
| 合并结果 | `scripts/university_results_merge.py` |
| 公共地址输入 | `scripts/build_university_address.py` |
| 地址规范化 | `python -m query_city_core.address.process` （串行） |
| 工作簿 | `scripts/build_excel.py` |
| 质量闸门 | `scripts/university_quality_check.py --input-dir <runDir>` |

域名确认、合并/停办判断由 Agent 依官方证据完成；官网抓取、单校结果落盘与覆盖校验由脚本完成。单校结果文件只能由 `university_fetch_runner.py` 写出/替换。

## 1. 生成城市高校名录

```powershell
$runDate = Get-Date -Format yyyy-MM-dd; $runTime = Get-Date -Format HHmmss
$runDir = "output/<标准城市名>/$runDate/Higher_Education/$runTime"; New-Item -ItemType Directory -Force $runDir | Out-Null
python -m query_city_core.address.city --city <用户城市> > "$runDir/city_context.json"
scripts/university_filter.py --city-context "$runDir/city_context.json"
```

脚本以 `city_context.json` 所在目录为运行目录，输出 `city_universities.json`/`xlsx`；后续中间文件全部写入 `$runDir`。

## 2. 确认域名并并发抓取

### 2.1 域名确认

每校 WebSearch 一次（校名+官网+校区+地址），确认官方域名与候选页，同时找合并/停办或无官网证据；不得为换域名重复搜索。`city_universities.json` 分批（每批 ≤20 所）写入 `domain_batches/domain_batch_<NN>.json`；每项含 `school_identifier`/`school_name`，确认后写回一种结果：

- 普通项：`home_url`、`official_domains`（裸主机名）、可选 `candidate_urls`（同域候选页 ≤3）；
- 无官网项：`no_official_site: true` + `evidence_url` + `reason`；
- 合并/停办项：`processing_status: "skipped"` + `skip_reason`（`merged`/`ceased_independent_operation`）+ `skip_reference`；
- 无法结论：保留输入加 `failure_reason`；禁止把“没搜到/打不开”写成 `no_official_site`/`skipped`。

官网判定：页面标题/站点名/正文须明确对应学校全名；可访问主站优先，`.edu.cn` 非硬性；招生、百科、第三方院校库与地图不算官网；跳转域名须有同次搜索或官方页面身份证据；候选页必须属于 `official_domains`。

写回后运行 `university_domain.py probe --run-dir <runDir>` 产出 `domain_probe_report.json`（逐个访问普通项主页，记录可达性、跳转终域、终页标题与机构名匹配及建议；探测不计 WebSearch 预算）。复核：主页跳转到未列入 `official_domains` 的域名且终页身份匹配 → 更新批次并入域名并把主页改为终址；主页失败且无法结论的学校按失败校处理。

运行 `university_domain.py merge --run-dir <runDir>` 汇总全部批次输出 `official_domain_manifest.json`；存在 `failure_reason` 时拒绝输出。失败校统一复检一次（再搜、更新、重汇总）；仍失败则停止并说明，不进抓取。

### 2.2 并发抓取

- 命令 `scripts/university_fetch_runner.py`（manifest/run-dir 按上一步文件路径；workers 默认 3；复检加 `--only-failures`）。
- `no_official_site`/`skipped` 由运行器直接写结果，不启动浏览器；普通项按 `--workers` 并发抓取。
- 先抓 `home_url` 并做首页身份校验（标题不含校名记 warning）；有 `candidate_urls` 时即使首页命中地址也继续抓完全部候选页；预算内按 campus/contact/overview 优先级跟随同域白名单相关链接（校区详情、学校概况/简介/章程/地址、联系我们；栏目类“简介/概况”如原校、产业学院、队伍概况不跟随）。
- 预算：默认每校 ≤3 页（访问失败也计入）；有候选页或多校区汇总线索（≥2 校区提示/链接，或单页 ≥2 个不同物理地址）放宽到 ≤6 页；同一校区详情只补抓一次；链接按 host+path 去重。
- 页面对象原样原子写入 `school_results/<school_identifier>.json`（失败页保留）；输出 `fetch_report.json`（每校状态、页数、是否有地址候选、首页身份告警）与 `retry_failures.json`。
- `retry_failures` 只复检一次：更新清单后同命令加 `--only-failures`；仍失败则停止，不进合并。

## 3. 合并结果

前提：全部学校有合法单校结果（`completed`/`skipped`/`no_official_site`），字段见 [单校结果文件规范](references/retrieval-result-format.md)。

运行 `university_results_merge.py --input-dir <runDir>/school_results --output <runDir>/university_retrieval_results.json`；脚本校验文件名、学校覆盖、处理状态与页面预算。

## 4. 生成公共地址输入

运行 `build_university_address.py --input <runDir>/university_retrieval_results.json --output <runDir>/address_records.json`，同时产出 `university_page_results.json`；要求名录数 = completed + skipped + no_official_site，遗漏 0。无官网学校生成一条空地址记录：`source_reference=evidence_url`、`attributes.abnormal_reason=reason`。

## 5. 处理地址

运行 `python -m query_city_core.address.process --input <runDir>/address_records.json --output <runDir>/processed_address_records.json`。

- 官网完整地址直接采用（地图只验证）；官网无地址且地图唯一兜底成功→采用地图地址；无官网学校按校名 POI 兜底；指向市外、规范化冲突或无合格兜底→留空。
- 不得残留未处理的地图错误；预期调用地图时请求数不得为 0。

## 6. 生成工作簿

运行 `build_excel.py --input <runDir>/processed_address_records.json --output <runDir>/高校建筑查询_<标准城市名>_<YYYY-MM-DD>.xlsx`。「高校信息」11 列，只含最终地址非空行；「异常校」9 列，覆盖最终地址为空（含无官网且地图未救回）学校，异常原因非空。

## 完成检查

- 域名批次与名录一一对应并已汇总；`failure_reason` 已统一复检一次；`domain_probe_report.json` 已复核并按跳转/身份问题更新批次。
- `fetch_report.json` 的 `campus_coverage` 已复核：`missing_campus_names` 仅指“详情页未抓且任何已抓页都未给地址”的真实缺口；`detail_page_not_fetched` 仅提示不告警。
- 同校多条无校区名地址按不同物理地址各保留一行；方向/距离描述与职责叙述句不产生行；`school_results/` 逐校覆盖、无重复遗漏；页面通常 ≤3（扩展条件成立 ≤6）。
- 地址处理无未处理错误；`map_match_status=needs_review` 行逐条复核，地图未确证时保留官网地址，不写无关 POI；工作簿可打开，两表列与行约束符合约定。
- 交付前运行 `university_quality_check.py --input-dir <runDir>` 且 `passed = true`：最终地址无 TEL/电话/传真/邮箱/邮编等联系词尾巴，不存在同校同路“有门牌与无门牌”并存重复行；命中时由 Agent 逐条兜底（补官方候选页或改批次后重跑），禁止静默放行。
- 官网未公开的校区地址按“官网未公开”口径记录说明；不引入 PDF/第三方来源补地址。

最终回复只给：标准城市名、名录学校数、域名/抓取状态计数、地址处理状态计数、最终地址行数、最终文件绝对路径；不展开逐校过程。
