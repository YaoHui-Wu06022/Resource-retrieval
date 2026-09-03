# web_search 类 Skill 模板

适用于“先有名单/种子，再逐官网页面取证”的城市查询 Skill。当前实例：
`query-city-universities`（前缀 `university_`）。

## 目录与角色文件

```text
<skill>/
  SKILL.md
  README.md
  AGENTS.md
  requirements.txt            # 只锁定 query-city-core==0.1.0
  references/<scene>-result-format.md
  scripts/
    <scene>_filter.py         # 找名单：基础名录筛选与标签
    <scene>_domain.py         # 域名阶段 CLI：probe 探测现用性 / merge 批次汇总 → manifest
    <scene>_page_fetch.py     # 单对象页面抓取策略与语义提取库
    <scene>_fetch_runner.py   # 并发抓取运行器（子进程调用 page_fetch）
    <scene>_results_merge.py  # 逐对象结果合并与覆盖校验
    build_<scene>_address.py  # 候选地点地址对 → 清洗/校验/去重 → address_records
    build_excel.py
    README.md、tests/
```

## 流程与阶段文件

```text
python -m query_city_core.address.city --city <城市>
  → city_context.json
<scene>_filter.py → <scene>_candidates.json（找名单）
Agent 分批 WebSearch 确认官网域名（domain_batches/*.json）
<scene>_domain.py probe → domain_probe_report.json（复核后写回批次）
<scene>_domain.py merge → official_domain_manifest.json
<scene>_fetch_runner.py → school_results/、fetch_report.json、retry_failures.json
<scene>_results_merge.py → university_retrieval_results.json
build_<scene>_address.py → address_records.json
python -m query_city_core.address.process → processed_address_records.json
scripts/build_excel.py → 高校信息 + 异常校工作簿
```

## 约定

- Agent 负责域名确认、合并/停办判断、探测报告与失败校复检；抓取、落盘
  与覆盖校验由脚本完成。
- 页面为原始单页结果，单对象结果文件只能由 `<scene>_fetch_runner.py` 写入或
  替换；失败校只允许一次统一复检。
- 公共字段遵循 `query_city_core/FIELD_NAMES.md`；场景字段（学校标识码、
  校区名等）只存在于 Skill 层 `attributes` 与 `references/`。
