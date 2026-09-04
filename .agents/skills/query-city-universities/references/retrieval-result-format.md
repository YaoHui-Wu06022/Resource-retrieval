# 单校结果文件规范

仅用于写入或审查 `school_results/<school_identifier>.json`；字段与结构以本文件为准，脚本校验结果为准。

## 文件规则

- 一文件一校，文件名 = `city_universities.json` 中的 `school_identifier`。
- 顶层直接保存单校对象，不用 `items` 包装；只允许本文件声明的字段，不填城市、学校名称、完整学校对象或 `stage`。

## completed

```json
{
  "school_identifier": "4144010558",
  "processing_status": "completed",
  "pages": []
}
```

`pages` 按访问顺序保存完整原始页面对象，原样保留，不重建、删改或只摘录字段；至少 1 页、至多 6 页，访问失败页也原样保留。只允许 `school_identifier`、`processing_status`、`pages` 三个字段。

## skipped

```json
{
  "school_identifier": "4144010000",
  "processing_status": "skipped",
  "skip_reason": "merged",
  "skip_reference": "https://example.edu.cn/official-evidence"
}
```

只允许四个字段；`skip_reason` 只能是 `merged` 或 `ceased_independent_operation`，`skip_reference` 必须是支持判断的 HTTP(S) 官方证据页面。

## no_official_site

```json
{
  "school_identifier": "4144010000",
  "processing_status": "no_official_site",
  "evidence_url": "https://example.gov.cn/official-record",
  "reason": "2026 年新设，未找到归属明确的独立官网"
}
```

只允许四个字段；`evidence_url` 必须是支持判断的官方证据页，`reason` 说明无官网或不可达的具体原因。
