# 政府来源结果格式

## `government_source.json`

每行政单位一份，Agent 写入；`inspect` 只校验读取，不代替 Agent 判断来源质量。

```json
{"stage":"basic_education_government_source","city_context":<city 原样>,"administrative_unit":<subdivisions 之一>,"processing_status":"completed","school_type_coverage":{"幼儿园":"covered","小学":"covered","初中":"covered","高中":"covered"},"coverage_notes":{"初中":"已核验层级与结论"},"items":[{...来源项...}]}
```

字段：

| 字段 | 取值 |
| --- | --- |
| `stage` | 固定 `basic_education_government_source` |
| `city_context` | 城市标准化结果原样 |
| `administrative_unit` | 必须是 `city_context.subdivisions` 之一 |
| `processing_status` | `completed`(items 非空且四类全 covered)/`partial`(items 非空且至少一类非 covered)/`no_official_source`(无 items)/`source_unusable`(无 items，含 source_unusable) |
| `school_type_coverage` | 至少含幼儿园/小学/初中/高中；状态限 `covered`/`partial`/`no_official_source`/`source_unusable` |
| `coverage_notes` | 非 `covered` 学段必填：已核验层级与结论 |
| `items` | 已确认采用并保存本地的来源 |

## 来源项（`items[]`）

| 字段 | 说明 |
| --- | --- |
| `source_title/publisher` | 来源标题/发布部门 |
| `publication_date` | 发布或更新日期；无法确认给空 |
| `landing_page_url/content_url` | 政府说明页/实际含名录的正文或附件 |
| `covered_school_types` | 实际覆盖类型（非空） |
| `contains_address` | 是否含学校地址 |
| `local_files` | 相对单位目录的原始文件名（非空） |
| `local_file_urls/derived_files/access_attempts` | 可选：文件名→URL、视觉等派生文件、访问审计 |
| `source_form_reason` | 仅无文本替代图片/PDF 填 `no_text_alternative` |

格式按后缀识别，Agent 不重复填写。分页/同构详情页全部页面写进同一来源 `local_files`（用 `local_file_urls` 保留逐页网址）；候选页、通知、未采用来源不写 `items`。

## `source_download_manifest.json`

```json
{"stage":"source_download_manifest","allowed_domain":"www.example.gov.cn","items":[{"file":"小学名录.xlsx","url":"https://..."}]}
```

命令：`download --manifest <清单> --output-dir <单位目录>`。

- `allowed_domain` 可选，给出后只接受该域（含子域）最终地址。
- 成功后原地回写 `final_url/http_status/size_bytes/access_attempts`，失败项加 `error`；顶层含 `errors/metrics`。
- zip 安全解一层可读文件，回写 `extracted_files`（GBK 名自动修复），zip 原件保留；解压失败进 `errors` 且返回非零，zip 留人工处理。

## `directory_link_manifest.json`

```json
{"stage":"directory_link_manifest","link_pattern":"/content/post_\\d+\\.html","allowed_domain":"www.example.gov.cn","items":[{"url":"https://.../index.html","note":"栏目"}]}
```

命令：`list-links --input <清单> --output <链接清单>`；输出每 URL 对应 `items[]`（含去重绝对 `links[]`、`final_url/http_status/page_title/access_attempts`），顶层 `errors/metrics`。Agent 复核后收录；候选不直接写入 `government_source.json`。

## 扫描件视觉结果（MinerU）

仅当来源登记 `source_form_reason=no_text_alternative` 才进入视觉分支。产物：

```json
{"stage":"vision_source_result","source_file":"名录.pdf.vision","pages":[{"page":1,"rows":[["学校","地址"],["学校名称","地址文字"]]}]}
```

`rows` 保留原始行列，不添加来源不存在的地址。

- 运行：`scripts/school_government_flow.py mineru-parse --source <government_source.json> --local-file <PDF文件名> --pages 15-33 [--output-dir <单位目录>]`。
- 逐页提交 MinerU URL 任务（`vlm`、`is_ocr=true`、`enable_table=true`），把返回 `table_body` HTML 还原为二维 `rows`；URL 不可达时回退本地上传。
- 派生文件名：PDF 名为 `<原名>.pdf` → 输出 `<原名>.pdf.vision.json`（`source_file` 为 `<原名>.pdf.vision`）；命令自动写回该来源 `derived_files`。
- 凭据：`.env` 的 `MINERU_ACCESS_KEY/MINERU_SECRET_KEY`（OpenXLab AK/SK→JWT），不写日志/输出。
- 页定位辅助：`mineru-inspect --source ... --local-file ... [--pages ...]` 输出逐页“有表/表题”摘要。
