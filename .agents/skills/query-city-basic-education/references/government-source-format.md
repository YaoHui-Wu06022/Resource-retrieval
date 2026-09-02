# 政府来源结果格式

## `government_source.json`

每个行政单位一份，由负责检索的 Agent 写入；`inspect` 只校验并读取，不代替 Agent 搜索来源或判断质量。

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

`city_context` 原样使用城市标准化结果；`administrative_unit` 必须原样取自其中 `subdivisions` 的一项。

| 字段 | 写入方 | 内容 |
| --- | --- | --- |
| `stage` | Agent 写入，脚本校验 | 固定 `basic_education_government_source`。 |
| `city_context` | 执行 Agent 原样写入 | 完整城市上下文（来自城市标准化结果）。 |
| `administrative_unit` | 同上 | 必须等于 `city_context.subdivisions` 中的一项。 |
| `processing_status` | Agent 判断 | 本行政单位政府名录来源的整体检索结果。 |
| `school_type_coverage` | Agent 判断 | 各学校类型的政府名录覆盖状态。 |
| `items` | Agent 写入，脚本读取 | 已确认采用并保存到本地的政府名录来源。 |

`school_type_coverage` 至少含幼儿园、小学、初中、高中；其他非高校类型按原文增加。值限 `covered`、`partial`、`no_official_source`、`source_unusable`。

一贯制/完中按覆盖学段计入四类覆盖：完全中学 = 初中 + 高中；九年一贯制学校 = 小学 + 初中；十二年一贯制学校 = 小学 + 初中 + 高中；十五年一贯制学校 = 幼儿园 + 小学 + 初中 + 高中。填写 `school_type_coverage` 与 `covered_school_types` 时据此判断，不按名称字面推断。

| `processing_status` | `items` | 四类必查覆盖 |
| --- | --- | --- |
| `completed` | 非空 | 全部 `covered`。 |
| `partial` | 非空 | 至少一类不是 `covered`。 |
| `no_official_source` | 空 | 全部 `no_official_source`。 |
| `source_unusable` | 空 | 至少一类 `source_unusable`，其余仅 `source_unusable` 或 `no_official_source`。 |

## 来源文件下载清单

输入：`source_download_manifest.json`，由公共层 `query_city_core.source_files.download_source_files` 执行。

```json
{
  "stage": "source_download_manifest",
  "allowed_domain": "www.example.gov.cn",
  "items": [
    {
      "file": "越秀区小学名录.xlsx",
      "url": "https://www.example.gov.cn/files/list.xlsx"
    }
  ]
}
```

`allowed_domain` 可选：给出时只接受最终地址在该域名（含子域）下的文件，跳转出域按失败记录。

命令：`scripts/build_school_address.py download --manifest <清单路径> --output-dir <行政单位目录>`

结果写回同一清单：每项增加 `final_url`、`http_status`、`size_bytes`、`access_attempts`，失败项增加 `error`；顶层 `errors` 与 `metrics` 汇总。Agent 再把文件名、最终网址与访问审计写入 `government_source.json` 对应来源项的 `local_files`、`local_file_urls`、`access_attempts`。

## 目录页链接清单

输入：`directory_link_manifest.json`，由公共层 `query_city_core.directory_links.collect_directory_links` 执行。

```json
{
  "stage": "directory_link_manifest",
  "link_pattern": "/content/post_\\d+\\.html",
  "allowed_domain": "www.example.gov.cn",
  "items": [
    {
      "url": "https://www.example.gov.cn/jyly/xx/index.html",
      "note": "小学栏目"
    }
  ]
}
```

`link_pattern`、`allowed_domain` 均可选：前者按正则过滤链接，后者限定允许域名。

命令：`scripts/build_school_address.py list-links --input <清单路径> --output <链接清单路径>`

输出：`stage = directory_links`，每个输入 URL 对应一个 `items[]`，`links[]` 为按页面顺序去重后的绝对地址候选。

```json
{
  "stage": "directory_links",
  "items": [
    {
      "url": "https://www.example.gov.cn/jyly/xx/index.html",
      "note": "小学栏目",
      "final_url": "https://www.example.gov.cn/jyly/xx/index.html",
      "http_status": 200,
      "page_title": "小学栏目",
      "links": [
        {
          "title": "天河区小学基本情况",
          "url": "https://www.example.gov.cn/jyly/xx/content/post_1.html"
        }
      ],
      "access_attempts": []
    }
  ],
  "errors": [],
  "metrics": {
    "item_count": 1,
    "page_count": 1,
    "link_count": 1,
    "error_count": 0
  }
}
```

Agent 复核 `links[]` 与 `errors` 后决定把哪些页面写入下载清单；候选链接不直接写入 `government_source.json`。

## 政府来源记录（`items[]`）

| 字段 | 类型 | 内容 |
| --- | --- | --- |
| `source_title` | string | 来源标题。 |
| `publisher` | string | 发布部门。 |
| `publication_date` | string | 发布或更新日期，无法确认时为空字符串。 |
| `landing_page_url` | string | 说明来源的政府页面。 |
| `content_url` | string | 实际含学校名录的正文或附件链接。 |
| `covered_school_types` | array | 该来源实际覆盖的学校类型。 |
| `contains_address` | boolean | 该来源是否提供学校地址。 |
| `local_files` | array | 相对行政单位目录的原始文件名，至少一项。 |
| `local_file_urls` | object | 可选；按 `local_files` 文件名记录每个文件的实际政府网址。 |
| `derived_files` | array | 可选；视觉处理等步骤生成的派生文件名。 |
| `access_attempts` | array | 可选；来源或详情页访问审计。 |

文件格式由读取脚本按 `local_files` / `derived_files` 后缀识别，Agent 不重复填写。分页 HTML 或同构详情页的全部本地页面写入同一来源的 `local_files`；详情页用 `local_file_urls` 保留逐页证据网址。候选页面、无名录通知和未采用来源不得写入 `items`。

## 视觉来源

有视觉能力时，对 `needs_vision` 文件生成 `<原文件名>.vision.json`：

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

`rows` 保留页面原始行列，不添加来源不存在的地址。生成后把文件名加入对应来源的 `derived_files`，再重跑来源检查；没有视觉能力时不创建该文件，也不运行本地 OCR。
