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
  - `image_reader.py`：图片标记为等待视觉识别。
  - `vision_reader.py`：读取视觉模型生成的 `vision_source_result` JSON。
  - `tables.py`：DataFrame 到纯文本二维表的转换。
- `collectors/`：官方来源收集。
  - `directory_links.py`：栏目页候选链接收集。
  - `source_files.py`：来源文件批量下载与审计回写。
  - `linked_pages.py`：名录页同构详情页批量保存。
- `extract/`：官方来源提取通用引擎。
  - `rules.py`：`FieldTerms` 场景词表、表头规则推断、重复 HTML 容器
    候选、来源文件检查。
  - `extract_utils.py`：索引/定位/键值字段/文本分段等通用提取工具。

## 修改记录

### 2026-09-02

- 新增本层；基础教育 Skill 的 `source_readers/` 迁移为
  `official/readers/`，公共层原有 `directory_links.py`、`linked_pages.py`、
  `source_files.py` 迁移为 `official/collectors/`，旧文件删除。
- 基础教育“检查 → 提取计划”中的表头识别、规则推断与重复 HTML 候选
  下沉为 `official/extract` 通用引擎；学校字段词表通过 `FieldTerms`
  由 Skill 注入，通用引擎不感知学校语义。
