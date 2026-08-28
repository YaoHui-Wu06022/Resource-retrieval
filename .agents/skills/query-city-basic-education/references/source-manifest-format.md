# 行政单位来源结果格式

## `sources.json`

每个行政单位单独保存一份 `sources.json`：

```json
{
  "schema_version": "1.0",
  "city": "标准城市名",
  "administrative_unit": {
    "name": "行政单位名称",
    "adcode": "行政区划代码",
    "level": "district"
  },
  "status": "completed",
  "school_type_coverage": {
    "幼儿园": "covered",
    "小学": "covered",
    "初中": "covered",
    "高中": "covered"
  },
  "sources": []
}
```

`administrative_unit` 原样使用城市标准化结果中的对象。`status` 使用 `completed`、`partial`、`no_official_source` 或 `source_unusable`。`school_type_coverage` 至少包含幼儿园、小学、初中和高中；政府来源出现的其他非高校类型按原文增加，值使用 `covered`、`partial`、`no_official_source` 或 `source_unusable`。

每个 `sources[]` 对象包含：

| 字段 | 内容 |
| --- | --- |
| `source_title` | 来源标题 |
| `publisher` | 发布部门 |
| `publication_date` | 发布或更新日期，无法确认时为空 |
| `landing_page_url` | 说明来源的政府页面 |
| `content_url` | 名录正文或附件的直接链接 |
| `source_format` | `html`、`xlsx`、`xls`、`docx`、`doc`、`pdf` 或图片格式 |
| `covered_school_types` | 该来源实际覆盖的学校类型 |
| `contains_address` | 该来源是否提供地址 |
| `local_files` | 相对于行政单位目录的原始文件名数组 |
| `derived_files` | 可选；派生文件名数组 |

`local_files` 必须非空。分页 HTML 的所有本地页面写入同一来源的 `local_files`，不得把候选页面或无名录通知写入来源。

## 视觉来源

有视觉能力的 Agent 对 `needs_vision` 文件生成 `<原文件名>.vision.json`：

```json
{
  "schema_version": "1.0",
  "stage": "vision_source_result",
  "source_file": "原文件名",
  "pages": [
    {
      "page": 1,
      "rows": [["学校", "地址"], ["学校名称", "地址文字"]]
    }
  ]
}
```

`rows` 保留页面中的原始行列，不添加来源不存在的地址。生成后把文件名加入对应来源的 `derived_files`，再重新运行来源检查。没有视觉能力时，不创建该文件，也不运行本地 OCR。
