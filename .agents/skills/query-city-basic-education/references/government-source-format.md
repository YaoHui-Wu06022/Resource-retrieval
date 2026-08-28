# 政府来源结果格式

## `government_source.json`

每个行政单位单独保存一份 `government_source.json`。该文件由负责来源检索的 Agent 写入，`build_school_address.py inspect` 只校验并读取，不代替 Agent 搜索来源或判断来源质量。

```json
{
  "stage": "basic_education_government_source",
  "city_context": {
    "stage": "city_context",
    "input_city": "广州",
    "city_name": "广州市",
    "province_name": "广东省",
    "subdivisions": [
      {
        "name": "越秀区",
        "adcode": "440104",
        "level": "district"
      }
    ]
  },
  "administrative_unit": {
    "name": "越秀区",
    "adcode": "440104",
    "level": "district"
  },
  "processing_status": "partial",
  "school_type_coverage": {
    "幼儿园": "covered",
    "小学": "covered",
    "初中": "no_official_source",
    "高中": "no_official_source"
  },
  "items": [
    {
      "source_title": "越秀区幼儿园和小学名录",
      "publisher": "越秀区教育局",
      "publication_date": "2026-08-01",
      "landing_page_url": "https://www.example.gov.cn/notice/1",
      "content_url": "https://www.example.gov.cn/files/schools.xlsx",
      "covered_school_types": ["幼儿园", "小学"],
      "contains_address": true,
      "local_files": ["越秀区幼儿园和小学名录.xlsx"]
    }
  ]
}
```

`city_context` 原样使用城市标准化结果；`administrative_unit` 原样使用其中 `subdivisions` 的当前行政单位对象。

| 字段 | 写入方 | 内容 |
| --- | --- | --- |
| `stage` | Agent 写入，脚本校验 | 固定为 `basic_education_government_source`。 |
| `city_context` | 主 Agent 传入，子 Agent 原样写入 | 完整城市上下文。 |
| `administrative_unit` | 主 Agent 传入，子 Agent 原样写入 | 必须等于 `city_context.subdivisions` 中的一项。 |
| `processing_status` | Agent 判断并写入 | 本行政单位政府名录来源的整体检索结果。 |
| `school_type_coverage` | Agent 判断并写入 | 各学校类型的政府名录覆盖状态。 |
| `items` | Agent 写入，脚本检查和读取 | 已确认采用并保存到本地的政府名录来源。 |

`school_type_coverage` 至少包含幼儿园、小学、初中和高中；政府来源出现的其他非高校类型按原文增加。每个值使用 `covered`、`partial`、`no_official_source` 或 `source_unusable`。

四类必查学校与 `processing_status` 的关系固定为：

| `processing_status` | `items` | 四类必查学校的覆盖状态 |
| --- | --- | --- |
| `completed` | 非空 | 全部为 `covered`。 |
| `partial` | 非空 | 至少一类不是 `covered`。 |
| `no_official_source` | 空 | 全部为 `no_official_source`。 |
| `source_unusable` | 空 | 至少一类为 `source_unusable`，其余只能为 `source_unusable` 或 `no_official_source`。 |

## 政府来源记录

每个 `items[]` 对象包含：

| 字段 | 类型 | 内容 |
| --- | --- | --- |
| `source_title` | string | 来源标题。 |
| `publisher` | string | 发布部门。 |
| `publication_date` | string | 发布或更新日期，无法确认时为空字符串。 |
| `landing_page_url` | string | 说明来源的政府页面。 |
| `content_url` | string | 实际包含学校名录的正文或附件链接。 |
| `covered_school_types` | array | 该来源实际覆盖的学校类型。 |
| `contains_address` | boolean | 该来源是否提供学校地址。 |
| `local_files` | array | 相对于行政单位目录的原始文件名，至少一项。 |
| `derived_files` | array | 可选；由视觉处理等步骤生成的派生文件名。 |

文件格式由读取脚本根据 `local_files` 和 `derived_files` 的后缀识别，Agent 不重复填写。分页 HTML 的所有本地页面写入同一来源的 `local_files`；不得把候选页面、无名录通知或未采用来源写入 `items`。

## 视觉来源

有视觉能力的 Agent 对 `needs_vision` 文件生成 `<原文件名>.vision.json`：

```json
{
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
