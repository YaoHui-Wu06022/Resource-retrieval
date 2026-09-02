---
name: query-city-universities
description: "根据中国城市筛选教育部普通高校名单，检索学校官网中的校区地址，经公共地址组件规范化和地图验证后生成高校信息 Excel。"
---

## 输入与运行条件

输入：一个中国城市。输出：该城市高校及校区的最终地址工作簿（「高校信息」+「异常校」两个工作表）。

- 环境未确认先询问；确认后全程使用同一环境。依赖：`openpyxl`、`playwright` 与 Playwright Chromium。
- 高校名单固定使用本 Skill `assets/` 中的普通高校、985、211 名单。
- 地址处理从环境变量或 `.env` 读取 `AMAP_KEY`。
- 缺依赖、密钥、浏览器或资产时停下说明缺项；不自装、不另写临时脚本复制固定逻辑，也不把未完成地图处理的结果当作完整结果。

全部输出写入 `output/<标准城市名>/<YYYY-MM-DD>/Higher_Education/<HHMMSS>/`。每次调用用新 `<HHMMSS>`，重新检索并生成全部结果，不覆盖旧运行目录。

## 执行边界与 Agent 分工

固定处理统一调用下表脚本，不另写临时脚本拆分、转换或组装抓取输出：

| 用途 | 命令 |
| --- | --- |
| 标准化城市、取下级行政区 | `python -m query_city_core.city` |
| 生成城市高校名录 | `scripts/filter_universities.py` |
| 域名确认 | 按批 WebSearch 确认，产出 `domain_batches/*.json`，再汇总为 `official_domain_manifest.json` |
| 并发抓取官网 | `scripts/run_university_fetch.py` |
| 合并逐校结果 | `scripts/merge_university_results.py` |
| 生成公共地址输入 | `scripts/build_university_address.py` |
| 规范化地址与地图兜底 | `python -m query_city_core.address.process` |
| 生成最终工作簿 | `scripts/build_excel.py` |

- 域名确认、合并/停办判断由 Agent 按官方证据完成；官网抓取、单校结果落盘与覆盖校验由脚本完成。
- Agent 负责域名确认与汇总复核、`fetch_report`/`retry_failures` 复检与全部下游固定处理。单校结果文件只能由 `run_university_fetch.py` 写出或替换。

## 1. 生成城市高校名录

```powershell
$runDate = Get-Date -Format yyyy-MM-dd
$runTime = Get-Date -Format HHmmss
$runDir = 'output/<标准城市名>/' + $runDate + '/Higher_Education/' + $runTime
New-Item -ItemType Directory -Force $runDir | Out-Null
python -m query_city_core.city --city <用户城市> > "$runDir/city_context.json"
scripts/filter_universities.py --city-context "$runDir/city_context.json"
```

`<标准城市名>` 用城市组件返回的规范名称，如 `深圳市`。脚本生成 `city_universities.json` 与 `city_universities.xlsx`；后续中间文件全部写入 `$runDir`，`filter_universities.py` 以 `city_context.json` 所在目录为运行目录。

## 2. 确认官网域名并并发抓取

### 2.1 域名确认（每校一次 WebSearch）

每所学校 WebSearch 一次（学校全名 + 官网 + 校区 + 地址），确认官方域名与候选页，同时寻找合并/停办或无独立官网的证据；不得为更换域名重复搜索。

把 `city_universities.json` 分成批次（每批 ≤ 20 所），逐批搜索确认，在 `$runDir/domain_batches/` 写 `domain_batch_<NN>.json`；每项含 `school_identifier` 与 `school_name`，确认后写回以下一种结果：

- 普通项：`home_url`、`official_domains`（裸主机名，可多个）、可选 `candidate_urls`（同域候选页，最多 3 个）；
- 无官网项：`no_official_site: true`、`evidence_url`、`reason`；
- 合并/停办项：`processing_status: "skipped"`、`skip_reason`（`merged` 或 `ceased_independent_operation`）、`skip_reference`；
- 无法给出合法结论：保留输入并加 `failure_reason`；禁止把“没搜到/打不开”伪造成 `no_official_site` 或 `skipped`。

官网判定：页面标题/站点名/正文须明确对应学校全名；可访问主站优先，`.edu.cn` 非硬性；招生、百科、媒体、第三方院校库与地图不算官网；跳转域名须有同次搜索证据；候选页必须属于 `official_domains`。

运行 `scripts/merge_domain_batches.py --run-dir <runDir>` 汇总全部批次，输出 `official_domain_manifest.json`；存在 `failure_reason` 时脚本拒绝输出。

只对失败校统一复检一次（再搜一次、更新批次后重新汇总）；复检仍失败则停止并说明失败学校，不进入抓取。

### 2.2 并发抓取

```text
scripts/run_university_fetch.py \
  --manifest <runDir>/official_domain_manifest.json \
  --run-dir <runDir> \
  --workers 3
```

- 普通项按 `--workers` 切给独立进程抓取；`no_official_site` 与 `skipped` 由运行器直接写出结果，不启动浏览器。
- 页面策略：先抓 `home_url`；已有非空地址候选即停；否则按 `candidate_urls`、再按页面同域相关链接（campus/contact/overview 顺序）补抓。
- 页数预算：默认每校 ≤ 3 页，访问失败也计入；页面出现多校区汇总线索（≥ 2 个校区提示或校区链接）且尚无地址时，预算自动放宽到 ≤ 6 页，同一校区详情只补抓一次。
- 页面对象原样原子写入 `school_results/<school_identifier>.json`，失败页保留。
- 输出 `fetch_report.json`（每校状态、页数、是否有地址候选）与 `retry_failures.json`（缺少合法结果的学校）。
- 只对 `retry_failures` 复检一次：更新清单 URL 后运行同命令加 `--only-failures`；复检仍失败则停止，不进合并。

## 3. 合并单校结果

- 前提：全部学校有合法单校结果（`completed`/`skipped`/`no_official_site`），字段见 [单校结果文件规范](references/retrieval-result-format.md)。
- 命令：`scripts/merge_university_results.py --input-dir <runDir>/school_results --output <runDir>/university_retrieval_results.json`
- 脚本校验文件名、学校覆盖、处理状态与页面预算后输出结果。

## 4. 生成公共地址输入

- 命令：`scripts/build_university_address.py --input <runDir>/university_retrieval_results.json --output <runDir>/address_records.json`
- 同时生成 `university_page_results.json`；要求名录数 = completed + skipped + no_official_site，遗漏为 0。
- 无官网学校生成一条空地址记录：`source_reference = evidence_url`，`attributes.abnormal_reason = reason`。

## 5. 处理地址

- 命令：`python -m query_city_core.address.process --input <runDir>/address_records.json --output <runDir>/processed_address_records.json`
- 规则：官网完整地址直接采用（地图只验证）；官网无地址且地图唯一兜底成功采用地图地址；无官网学校按校名做 POI 兜底；指向城市外、规范化冲突或无合格兜底结果时留空。
- 不得存在未处理的地图错误；预期调用地图时请求数不得为零。

## 6. 生成最终工作簿

- 命令：`scripts/build_excel.py --input <runDir>/processed_address_records.json --output <runDir>/高校建筑查询_<标准城市名>_<YYYY-MM-DD>.xlsx`
- 「高校信息」十一列，只含最终地址非空行；「异常校」八列，覆盖最终地址为空的学校（含无官网且地图未救回），异常原因非空。

## 完成检查

- 域名批次与 `city_universities.json` 一一对应且已汇总；`failure_reason` 学校已统一复检；`fetch_report.json` 已复核。
- `school_results/` 逐校覆盖名录，无重复或遗漏；`retry_failures.json` 学校仅复检一次，无第三次检索。
- 页面均为原始单页结果，通常 ≤ 3 页（校区扩展条件成立时 ≤ 6 页）。
- 公共地址处理无未处理错误；工作簿可打开，两表列与行约束符合约定。

最终回复只说明：标准城市名、名录学校数、域名/抓取状态计数、地址处理状态计数、最终地址行数和最终文件绝对路径；不展开逐校检索过程。
