# 政府资料类 Skill 模板

适用于“政府公开名单/附件”来源的城市查询 Skill。当前实例：
`query-city-basic-education`（前缀 `school_`）与
`query-city-medical-institutions`（前缀 `medical_`）。

## 目录与角色文件

```text
<skill>/
  SKILL.md                    # 执行协议（来源检索、复核、命令、完成检查）
  README.md                   # 本层职责、文件功能与修改记录
  AGENTS.md                   # Python 操作规范（各 Skill 同一副本）
  requirements.txt            # 只锁定 query-city-core==0.1.0
  references/<scene>-source-format.md
  scripts/
    <scene>_government_flow.py  # CLI：list-links/download/collect-details(可选) + inspect/extract
    <scene>_common.py           # 词表、记录构造/规范化、去重、异常判断与 Excel 领域辅助
    build_excel.py              # 工作簿薄包装（区级 + 城市总表）
    README.md、tests/
```

## 流程与阶段文件

```text
python -m query_city_core.address.city --city <城市>
  → city_context.json
按 subdivisions 建同名目录，逐行政单位执行检索
  → <行政单位>/government_source.json
     （顶层含完整 city_context 与 administrative_unit，来源默认按区检索）
<scene>_government_flow.py inspect --sources <行政单位>/government_source.json
  → <行政单位>/extraction_plan.json（Agent 复核并设 approved/review_status）
<scene>_government_flow.py extract --plan <行政单位>/extraction_plan.json
  → <行政单位>/address_records.json（场景去重后，空地址记录保留）
python -m query_city_core.address.process（逐行政单位串行）
  → <行政单位>/processed_address_records.json（address_mode=government_list，POI 兜底）
scripts/build_excel.py --input-dir <运行目录> --output <城市总表>
  → 每个行政单位区级工作簿 + 城市总表
```

## 约定

- Agent 负责来源检索、质量/覆盖判断与提取计划复核；脚本负责类型规范、
  去重、地址路由与工作簿格式。
- `government_source.json`、`extraction_plan.json` 的 schema 由各 Skill 的
  `references/` 登记；公共字段遵循 `query_city_core/FIELD_NAMES.md`。
- 异常行由 `build_excel.py` 从 processed 结果推导：最终地址为空且无可用
  官方原文（或带 `abnormal_reason`），不设独立异常清单文件。
- `inspect`/`extract` 只调用公共 `official.extract` 引擎，Skill 层只提供
  词表、来源清单校验与记录构造。
- 可选采集子命令（`list-links`/`download`/`collect-details`）按场景来源
  形态启用，直接复用 `official.collectors`。
