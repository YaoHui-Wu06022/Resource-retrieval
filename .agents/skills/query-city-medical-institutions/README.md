# query-city-medical-institutions 医疗机构检索 Skill

## 本层职责

按中国城市直接下级行政单位检索政府公开的持证/备案医疗机构名单，整理机构
名称、官方类型、级别和执业地址并生成区级与城市汇总 Excel。执行流程见
`SKILL.md`，遵循政府资料 Skill 模板（`doc/government-source-skill-template.md`）。

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
| `references/medical-source-format.md` | `government_source.json`（每区一份）与提取阶段格式规范。 |
| `scripts/medical_government_flow.py` | 政府资料流程 CLI：`list-links` / `download` / `collect-details` / `platform-query` / `inspect` / `extract`。 |
| `scripts/medical_common.py` | 医疗记录构造、执业地址拆分、外市剔除、跨来源去重。 |
| `scripts/medical_scope.py` | 城市级跨目录去重、按最终物理地址分桶、机构类型大类归并。 |
| `scripts/build_excel.py` | 汇总各行政单位 processed 结果，跨目录去重后按物理地址分桶生成区级工作簿与城市总表。 |
| `scripts/medical_quality_check.py` | 交付前质量闸门：平台数量下界、大类覆盖与来源完整检查。 |

## 修改记录

### 2026-09-03

- 删除自研来源解析器（`medical_source_parsers.py`、
  `build_medical_address_records.py`），统一走
  `medical_government_flow.py` 的公共 inspect/extract 链路；
  废除 `anomaly_records.json` 阶段，异常行由 `build_excel.py` 从
  processed 结果推导；`extract` 重新接入跨来源去重。
- `government_source.json` 顶层改为内嵌完整 `city_context`；
  `medical_government_flow.py` 补齐与基础教育一致的
  `list-links` / `download` / `collect-details` 子命令。
- 医疗流程改为按直接下级行政单位默认分区检索：每区目录一份
  `government_source.json`（顶层 `city_context` + `administrative_unit`），
  地址记录 `subdivision_scope=subdivision`，`build_excel.py` 改为
  `--input-dir` 汇总各行政单位结果并生成区级与城市工作簿。
- 城市总表改为“机构信息”汇总表 + 各区工作表结构，异常机构表只保留在
  每区工作簿，总表不再包含异常机构表。
- 工作簿显示规则：机构级别为“未定级/无定级/无级别”时输出为空列，
  地址记录 JSON 中仍保留官方原文。
- SKILL.md 全文重排为整段行（不做 80 列手动折行），并压缩检索位置与
  顺序、执行边界、完成检查等表述；只描述栏目类型与查找次序，不写
  具体网址。

### 2026-09-04

- 检索层级改为“结果按区交付、来源先市后区”：市级统一注册查询平台/
  市级发证全量先行，区级全量名单补充校正，省级名单补充，个案公示仅佐证；
  平台页面“区发证信息以各区卫健局为准”等口径记入来源项并写入最终说明。
- 新增政府注册查询平台 `query_platform` 来源形态与 `platform-query`
  抓取子命令（原始 JSONP 页证据 + 汇总记录），平台官方快照即合格证据。
- 区级归属改为城市级跨目录去重后按最终物理地址分桶；无地址异常行保留
  在来源单位目录异常表。
- 新增硬性质量闸门 `medical_quality_check.py`：平台数量下界（默认 90%）、
  平台大类缺失阻断、无 ready 全量来源阻断，输出 `quality_report.json`。
