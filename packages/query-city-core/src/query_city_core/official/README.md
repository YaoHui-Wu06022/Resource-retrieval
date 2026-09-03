# official 官方数据框架

## 本层职责

面向“政府公开名单/官网附件”类来源的通用读取、收集与提取能力；
本层不包含学校、医院或机关的业务语义，场景词表由 Skill 注入。

## 目录结构

- `readers/`：按文件格式读取官方来源。
  - `__init__.py`：格式探测与统一入口
    （`detect_source_format`、`load_source_html`、`load_source_tables`、
    `normalize_text`）。
  - `html_reader.py`：HTML/Word 读取，Word 经 LibreOffice 转 HTML。
  - `spreadsheet_reader.py`：Excel/CSV 表格读取。
  - `pdf_reader.py`：PDF 原生文字层与表格检测。
  - `vision_reader.py`：图片标记、视觉模型调用与 `vision_source_result`
    JSON 读取合并于同一文件。
  - `tables.py`：DataFrame 到纯文本二维表的转换。
- `collectors/`：官方来源收集。
  - `directory_links.py`：栏目页候选链接收集。
  - `source_files.py`：来源文件批量下载与审计回写。
  - `archive_files.py`：zip 附件下载后的安全解压与内部可读文件登记。
  - `linked_pages.py`：名录页同构详情页批量保存。
- `extract/`：官方来源提取通用引擎。
  - `rules.py`：`FieldTerms` 场景词表、表头规则推断、重复 HTML 容器
    候选、来源文件检查。
  - `engine.py`：通用 `inspect_government_source` /
    `extract_government_records` 执行入口。
  - `extract_utils.py`：索引/定位/键值字段/文本分段等通用提取工具。

## 修改记录

### 2026-09-02

- 新增本层；基础教育 Skill 的 `source_readers/` 迁移为
  `official/readers/`，公共层原有 `directory_links.py`、`linked_pages.py`、
  `source_files.py` 迁移为 `official/collectors/`，旧文件删除。
- 基础教育“检查 → 提取计划”中的表头识别、规则推断与重复 HTML 候选
  下沉为 `official/extract` 通用引擎；学校字段词表通过 `FieldTerms`
  由 Skill 注入，通用引擎不感知学校语义。

### 2026-09-03

- 医疗机构 Skill 接入同一引擎（`medical_government_flow.py`），
  通过 `FieldTerms` 与规则修饰注入医疗词表，公共引擎不新增场景语义。
- `image_reader.py` 并入 `vision_reader.py`；后者支持图片 needs_vision
  标记、DashScope 兼容视觉调用（key/模型/base 从 `.env` 或环境读取）
  与 `vision_source_result` 读取。
- `download` 链路新增 zip 自动安全解压：仅解一层并保留 zip 内相对路径，
  成功项写回 `extracted_files`（可含 `skipped_entries`），zip 原件保留；
  解压失败进入清单 `errors` 且不删除压缩包。
