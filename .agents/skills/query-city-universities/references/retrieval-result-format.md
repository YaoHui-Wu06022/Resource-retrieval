# 单校结果文件规范

仅在写入或审查 `school_results/<school_identifier>.json` 时读取本文件。

## 文件规则

- 一文件一校；文件名 = `city_universities.json` 中的学校标识码（如 `4144010558.json`）。
- 顶层直接保存单校对象，不用 `items` 包装；不填城市、学校名称、完整学校对象或 `stage`。

## 正常处理（completed）

未依官方证据确认学校合并或停止独立办学时，使用：

```json
{
  "school_identifier": "4144010558",
  "processing_status": "completed",
  "pages": []
}
```

`pages` 按访问顺序保存每次 `fetch_official_universities.py` 返回的完整原始页面对象，原样保留，不重建、删改或只摘录候选字段。

- 至少 1 页；通常 ≤ 3 页；页面出现多校区汇总线索（≥ 2 个校区提示或校区链接）且尚无地址时，运行器自动把预算放宽到 ≤ 6 页，同一校区详情只补抓一次。
- 页面访问失败但未确认合并/停办时仍为 `completed`，并保留失败页。
- 只允许 `school_identifier`、`processing_status`、`pages` 三个字段。

## 跳过处理（skipped）

同次搜索已用明确官方证据确认学校合并或停止独立办学时，使用：

```json
{
  "school_identifier": "4144010000",
  "processing_status": "skipped",
  "skip_reason": "merged",
  "skip_reference": "https://example.edu.cn/official-evidence"
}
```

- `skip_reason` 只能是 `merged` 或 `ceased_independent_operation`；`skip_reference` 必须是支持判断的 HTTP(S) 官方证据页面。
- 跳过结果不填 `pages`，不进地图服务；只允许上述 4 个字段。

## 无官网处理（no_official_site）

域名确认阶段确认学校没有归属明确的独立官网（例如新设校），或官网域名不可达且无同次搜索官方候选时，使用：

```json
{
  "school_identifier": "4144010000",
  "processing_status": "no_official_site",
  "evidence_url": "https://example.gov.cn/official-record",
  "reason": "2026 年新设，未找到归属明确的独立官网"
}
```

- `evidence_url` 必须是支持该判断的官方证据页；`reason` 说明无官网或不可达的具体原因。
- 不填 `pages`，直接进入地址处理；地图按学校名称尝试 POI 兜底，无法救回时进入「异常校」。
- 只允许上述 4 个字段。

## 汇总边界

- 批量抓取由 `scripts/run_university_fetch.py` 统一写入 `school_results/<学校标识码>.json`，`no_official_site` 结果由同一运行器直接写出；主 Agent 不手工改写。
- 共享汇总文件只由 `scripts/merge_university_results.py` 生成，以脚本校验结果为准。
