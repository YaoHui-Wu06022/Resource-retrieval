# 政府来源结果格式

## `government_source.json`

每个行政单位一份，由 Agent 写入；`inspect` 只校验读取，不代替 Agent 判断来源质量。

```json
{
  "stage": "basic_education_government_source",
  "city_context": {"stage": "city_context", "input_city": "广州", "city_name": "广州市", "province_name": "广东省", "subdivisions": [{"name": "越秀区", "adcode": "440104", "level": "district"}]},
  "administrative_unit": {"name": "越秀区", "adcode": "440104", "level": "district"},
  "processing_status": "partial",
  "school_type_coverage": {"幼儿园": "covered", "小学": "covered", "初中": "no_official_source", "高中": "no_official_source"},
  "coverage_notes": {"初中": "区级未发布独立初中名录，已核验市级义务教育招生名单后仍无可采用来源", "高中": "区级未发布独立高中名录；已核验广州市高中阶段招生学校名单（市级，含校址所在区）后按区采用"},
  "items": [{
    "source_title": "越秀区幼儿园和小学名录",
    "publisher": "越秀区教育局",
    "publication_date": "2026-08-01",
    "landing_page_url": "https://www.example.gov.cn/notice/1",
    "content_url": "https://www.example.gov.cn/files/schools.xlsx",
    "covered_school_types": ["幼儿园", "小学"],
    "contains_address": true,
    "local_files": ["越秀区幼儿园和小学名录.xlsx"]
  }]
}
```

| 字段 | 内容 |
| --- | --- |
| `stage` | 固定 `basic_education_government_source`。 |
| `city_context` | 原样使用城市标准化结果。 |
| `administrative_unit` | 必须原样取自 `city_context.subdivisions` 的一项。 |
| `processing_status` | 本行政单位整体检索结果，取值见下。 |
| `school_type_coverage` | 至少含幼儿园、小学、初中、高中；状态限 `covered`/`partial`/`no_official_source`/`source_unusable`。 |
| `coverage_notes` | 可选对象；键为学段，值为非空说明。某学段状态不是 `covered` 时必填该学段说明，写清已完成检索层级与结论。 |
| `items` | 已确认采用并保存到本地的来源。 |

`no_official_source`/`source_unusable` 只表示按该学段首选与回退层级完成核验后仍无可用政府名录，不等于该行政单位没有该学段学校。学段检索起点：高中以市级（上级教育部门 / 市招生考试机构 / 市政府数据平台）为首要层级；幼儿园/小学/初中以区级为首要层级，缺失时再回退市级。市级名录若带“校址所在区 / 行政区”等字段，应按行政单位过滤后作为该单位来源采用，不能因名录覆盖全市而跳过；市级名录若无可拆分行政单位字段，不得整表归入任一行政单位，须在 `coverage_notes` 说明并继续找区级或可拆分来源。

`processing_status` 与 `items`/覆盖的组合：

| `processing_status` | `items` | 四类覆盖 |
| --- | --- | --- |
| `completed` | 非空 | 全部 `covered` |
| `partial` | 非空 | 至少一类不是 `covered` |
| `no_official_source` | 空 | 全部 `no_official_source` |
| `source_unusable` | 空 | 至少一类 `source_unusable`，其余仅 `source_unusable` 或 `no_official_source` |

## 来源项（`items[]`）

| 字段 | 类型 | 内容 |
| --- | --- | --- |
| `source_title` | string | 来源标题。 |
| `publisher` | string | 发布部门。 |
| `publication_date` | string | 发布/更新日期，无法确认时空字符串。 |
| `landing_page_url` | string | 说明来源的政府页面。 |
| `content_url` | string | 实际含名录的正文或附件链接。 |
| `covered_school_types` | array | 该来源实际覆盖的学校类型（非空）。 |
| `contains_address` | boolean | 是否提供学校地址。 |
| `local_files` | array | 相对行政单位目录的原始文件名（非空）。 |
| `local_file_urls` | object | 可选；`local_files` 文件名 → 实际政府网址。 |
| `derived_files` | array | 可选；视觉等步骤生成的派生文件。 |
| `source_form_reason` | string | 可选；仅无文本替代的图片/PDF 填 `no_text_alternative`。 |
| `access_attempts` | array | 可选；访问审计。 |

文件格式按后缀识别，Agent 不重复填写。分页/同构详情页全部页面写入同一来源的 `local_files`，用 `local_file_urls` 保留逐页网址；候选页面、通知和未采用来源不写入 `items`。

## 下载清单（`source_download_manifest.json`）

```json
{
  "stage": "source_download_manifest",
  "allowed_domain": "www.example.gov.cn",
  "items": [{"file": "小学名录.xlsx", "url": "https://www.example.gov.cn/files/list.xlsx"}]
}
```

命令：`download --manifest <清单> --output-dir <行政单位目录>`

- `allowed_domain` 可选；给出时只接受该域名（含子域）下的最终地址。
- 成功后清单原地写回 `final_url`/`http_status`/`size_bytes`/`access_attempts`，失败项加 `error`；顶层汇总 `errors`/`metrics`。
- zip：安全解压一层可读文件，登记 `extracted_files`（GBK 文件名自动修复），zip 原件保留；入选来源用解压文件，不登记 zip。
- 解压失败（损坏/加密/越界/超限/无可读文件）进 `errors` 且返回非零，zip 保留人工处理。

## 目录链接清单（`directory_link_manifest.json`）

```json
{
  "stage": "directory_link_manifest",
  "link_pattern": "/content/post_\\d+\\.html",
  "allowed_domain": "www.example.gov.cn",
  "items": [{"url": "https://www.example.gov.cn/jyly/xx/index.html", "note": "小学栏目"}]
}
```

命令：`list-links --input <清单> --output <链接清单>`

- `link_pattern`/`allowed_domain` 可选。
- 输出 `stage = directory_links`：每个输入 URL 对应一个 `items[]`，含去重后的绝对地址 `links[]`、`final_url`、`http_status`、`page_title`、`access_attempts`；顶层含 `errors`/`metrics`。
- Agent 复核后决定收录；候选链接不直接写入 `government_source.json`。

## 视觉来源（`<原文件名>.vision.json`）

仅当来源项已登记 `source_form_reason = no_text_alternative` 才可进入视觉分支：

```json
{
  "stage": "vision_source_result",
  "source_file": "原文件名",
  "pages": [{"page": 1, "rows": [["学校", "地址"], ["学校名称", "地址文字"]]}]
}
```

`rows` 保留原始行列，不添加来源不存在的地址。生成后把文件加入对应来源的 `derived_files` 并重跑检查；没有视觉能力时不创建该文件、不运行本地 OCR。

已配置视觉模型（`VISION_API_KEY`/`VISION_API_BASE_URL`/`VISION_MODEL`）时，可用核心库函数 `query_city_core.official.readers.vision_reader.transcribe_image_to_vision_result(图片路径, 输出路径)` 自动转录，输出路径写 `<原文件名>.vision.json`。
