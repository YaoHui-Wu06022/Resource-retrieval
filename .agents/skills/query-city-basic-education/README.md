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
