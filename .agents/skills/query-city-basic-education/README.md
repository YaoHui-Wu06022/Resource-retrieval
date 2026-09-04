# query-city-basic-education 基础教育检索 Skill

## 本层职责

按中国城市的直接下级行政单位检索政府公开的非高校学校名录，提取学校与
地址并生成区级和城市汇总 Excel。执行流程见 `SKILL.md`，遵循政府资料
Skill 模板（`doc/government-source-skill-template.md`）。

## 目录结构

- `references/`：政府来源与提取阶段格式规范。
- `scripts/`：固定处理脚本（角色见 `scripts/README.md`）。
- `scripts/tests/`：脚本测试。
- `requirements.txt`：锁定共享运行库 `query-city-core==0.1.0`。

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `SKILL.md` | 执行规范：来源检索、提取计划复核、地址处理与工作簿生成。 |
| `AGENTS.md` | 本 Skill Python 代码操作规范。 |
| `references/government-source-format.md` | `government_source.json` 与来源清单/提取计划阶段格式。 |
| `scripts/school_government_flow.py` | 政府资料流程 CLI：`list-links` / `download` / `collect-details` / `inspect` / `preview` / `extract`。 |
| `scripts/school_common.py` | 学校词表、记录构造、类型/校区规范化、按名称+地址去重。 |
| `scripts/build_excel.py` | 生成行政单位表与城市总表（学校信息 + 异常校）。 |

## 修改记录

### 2026-09-04（文档去重）

- SKILL.md 与 `references/government-source-format.md` 去重：状态语义与
  `coverage_notes` 填写内容要求只保留在执行规范；参考文档只保留字段与
  文件格式约束。
- SKILL.md `download` 小节不再重复 zip 解压规则（见参考文档下载清单）；
  视觉来源小节改为指向参考文档视觉一节，无视觉配置的兜底（不创建
  `<原文件名>.vision.json`、不运行本地 OCR、显式 `no_vision_capability`
  跳过）保留在 SKILL.md。

### 2026-09-04

- 扫描图片/PDF 转录改由 MinerU v4 API 完成：新增
  `school_government_flow.py mineru-parse`（逐页 URL/上传任务 →
  `<原名>.pdf.vision.json`，自动写回 `derived_files`）与可选
  `mineru-inspect`（整档逐页表格摘要）；凭据为 `.env` 的
  `MINERU_ACCESS_KEY/MINERU_SECRET_KEY`（OpenXLab AK/SK → JWT），
  原 `VISION_*` 配置与 DashScope 兼容 VLM 代码路径移除。
- 新增 `scripts/review.py` 收编复核辅助：支持页/表定位、校名与地址列、
  固定类型/性质、类型列、排除行、向下填充与“区单元格缺失即剔除规则”，
  取代运行目录内的 `approve_plan2.py` 临时脚本。
- `school_common.py` 非校名识别补纯数字行与“招生计划/计划招生”前缀，
  避免 MinerU 对合计/续表行的列合并产生伪记录。
- SKILL.md 检索起点按学段分层：高中以市级（上级教育部门 / 市招生考试机构 /
  市政府数据平台）为首要层级，区级只作补充核验；幼儿园/小学/初中以区级为
  首要层级，缺失时回退市级。市级名录无“校址所在区”等可拆分字段时不得
  整表归入任一行政单位。
- SKILL.md 层级回退约束：任何学段在首选层级找不到可用名录时，必须沿
  该学段路径继续核验（高中为市级；幼儿园/小学/初中为区级并回退市级）；
  市级名录带“校址所在区”时按区过滤采用。`no_official_source` 语义限定
  为“完成学段首选与回退层级核验后仍无政府名录”，不与“该区没有该学段
  学校”混同。
- `government_source.json` 新增可选顶层字段 `coverage_notes`：非
  `covered` 学段必须填写检索层级与结论，缺失时脚本校验不通过。

### 2026-09-03

- 收敛为政府资料模板：删除 `build_school_address.py`、
  `inspect_government_source.py`、`extract_school_records.py`、
  `normalize_school_records.py`，功能并入
  `school_government_flow.py` 与 `school_common.py`。
- `inspect` 命令统一使用 `--sources` 参数；脚本名从
  `build_school_address.py` 改为 `school_government_flow.py`。
- 移除历史 README 中已删除文件（`scripts/source_readers/` 等）的过时描述。

### 2026-09-03（文档修订）

- SKILL.md 工作簿列清单与 `build_excel.py` 实际输出对齐：学校信息表补齐
  “查询日期”列，异常校表列序改为“…发布日期、异常原因、信息来源、查询
  日期”，删除不存在的“地图匹配状态”列。
- README 文件功能表补齐 `preview` 子命令，与 SKILL.md 流程一致。
