# 单校结果文件规范

仅用于写入/审查 `school_results/<school_identifier>.json`；字段与结构以本文件为准，脚本校验结果为准。

规则：一文件一校，文件名 = 名录中的 `school_identifier`；顶层直接保存单校对象（不用 `items`/`stage`/城市等包装）；只允许本文件声明字段。

## completed

```json
{"school_identifier":"4144010558","processing_status":"completed","pages":[]}
```

只允许三字段。`pages` 按访问顺序原样保存完整原始页面对象（不重建、删改或摘录），至少 1 页、至多 6 页，访问失败页也保留。

## skipped

```json
{"school_identifier":"4144010000","processing_status":"skipped","skip_reason":"merged","skip_reference":"https://example.edu.cn/official-evidence"}
```

只允许四字段；`skip_reason` 限 `merged`/`ceased_independent_operation`；`skip_reference` 必须是支撑判断的 HTTP(S) 官方证据页。

## no_official_site

```json
{"school_identifier":"4144010000","processing_status":"no_official_site","evidence_url":"https://example.gov.cn/official-record","reason":"2026 年新设，未找到归属明确的独立官网"}
```

只允许四字段；`evidence_url` 必须是官方证据页；`reason` 说明无官网/不可达的具体原因。
