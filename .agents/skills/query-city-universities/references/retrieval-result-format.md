# 单校结果文件规范

仅在写入或审查 `school_results/<school_identifier>.json` 时读取本文件。

## 文件规则

- 一个文件只保存一所学校的结果。
- 文件名必须是 `city_universities.json` 中的学校标识码，例如 `4144010558.json`。
- 文件顶层直接保存单所学校对象，不使用 `items` 包装。
- 不填写城市、学校名称、完整学校对象或 `stage`。

## 正常处理

负责该校的 Agent 未依据官方证据确认学校已合并或停止独立办学时，使用：

```json
{
  "school_identifier": "4144010558",
  "processing_status": "completed",
  "pages": []
}
```

`pages` 按访问顺序保存每次 `fetch_official_universities.py` 返回的完整原始页面对象，不得重建、删改或只摘录候选字段。

- 至少保存一个页面。
- 通常最多三页。
- 符合校区详情扩展条件时最多六页。
- 页面访问失败但未确认学校合并或停止独立办学时，仍为 `completed`，并保留失败页面。

除 `school_identifier`、`processing_status` 和 `pages` 外，不得增加其他字段。

## 跳过处理

负责该校的 Agent 在同次搜索中已用明确官方证据确认学校合并或停止独立办学时，使用：

```json
{
  "school_identifier": "4144010000",
  "processing_status": "skipped",
  "skip_reason": "merged",
  "skip_reference": "https://example.edu.cn/official-evidence"
}
```

`skip_reason` 只能是：

- `merged`
- `ceased_independent_operation`

`skip_reference` 必须是支持判断的 HTTP(S) 官方证据页面。跳过结果不填写 `pages`，也不进入地图服务。

除 `school_identifier`、`processing_status`、`skip_reason` 和 `skip_reference` 外，不得增加其他字段。

## 汇总边界

子 Agent 只写自己负责学校的独立文件，不创建或修改 `university_retrieval_results.json`。主 Agent 使用 `scripts/merge_university_results.py` 生成共享汇总文件，并以脚本校验结果为准。
