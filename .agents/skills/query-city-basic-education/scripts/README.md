# scripts 处理脚本

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `school_government_flow.py` | 政府资料流程 CLI：`list-links` / `download` / `collect-details` / `inspect` / `preview` / `extract`；来源清单校验与引擎调用。 |
| `school_common.py` | 学校字段词表、记录构造、类型/办学性质规范、校区拆分、官方一贯制标记判型、POI 别名与按名称+地址去重。 |
| `build_excel.py` | 生成行政单位与城市总表（学校信息 + 异常校），异常行从 processed 推导。 |

## 修改记录

### 2026-09-04

- `school_government_flow.py` 来源清单校验新增顶层字段 `coverage_notes`
  （对象：学段 → 非空说明），并强制 `school_type_coverage` 中每个非
  `covered` 学段必须提供说明；用于落实“上级层级回退与缺口依据可复核”。
- `tests/test_build_school_records.py` 补齐 `coverage_notes` 接受、
  缺失、非法值与全 covered 可省略四类用例。

### 2026-09-03

- 由 `build_school_address.py`、`inspect_government_source.py`、 `extract_school_records.py`、`normalize_school_records.py` 收敛为 `school_government_flow.py` + `school_common.py`； `inspect` 参数统一为 `--sources`。
- 表头词表增加“单位名称”；来源引用不再二次包装 URL。
- 新增同来源跨校区唯一类型回填与同校区唯一地址回填，并调整为先补全 再去重；地址记录 attributes 增加 `subdivision_scope=subdivision`。
- `school_common.py` 校区地址拆分改为逐级递归：外层校区标签拆出后， 若残余地址仍含内层校区标签（如“小学部校区：（净慧校区）…”），继续 拆分并把内层标签拼接进校名（如“…小学部校区净慧校区”），最大嵌套 5 层防死循环；例如越秀区知用学校地址现可拆出中学部校区与净慧、 光孝、祝寿三个小学部子校区。
- `school_common.py` 新增按校名官方标记判型：名称含 `（九年一贯制）` `（十二年一贯制）` `（十五年一贯制）` 时自动使用对应一贯制学校类型， 在学部后缀推断之后、来源类型之上生效；无标记时行为不变。
- `school_common.py` 校区拆分改为链式标签扫描：支持“本校/正校/总校/ 分校”与“南校区地址”等标签写法及冒号、空格、破折号分隔；中段标签 不再吞并前段地址。无法唯一确定校区边界时保留原文并写入 `attributes.address_ambiguity`，由 `build_excel.py` 转入异常校复核。
- `school_common.py` 常量复用整理：校区单位词、学段词、禁用字符、 分隔符与地址裁剪字符集收敛为单一词表/常量，校区正则由常量组合生成； 纯内部重构，输出行为不变。
- `school_government_flow.py` 新增 `preview` 子命令，按已批准规则逐文件 统计将被提取的行并报告缺行、重叠与类型分布；缺行/重叠/待批准时非零退出。
- `school_government_flow.py` `preview` 支持视觉来源配对：原图（如 PNG/JPG） 自身无规则但存在已批准的 `<原文件名>.vision.json` vision 规则时，跳过 原图检查、改由派生文件统计行覆盖，不再误报“没有已批准的表格提取规则”。
- `school_government_flow.py` `preview` 统计改为按规则定位的表独立计算： 修复同一文件多张表行号跨表误报重叠，并应用 `required_cell_values`、 `fill_down_columns` 与排除行语义，候选/覆盖行数贴近实际 extract 口径。
- `school_government_flow.py` 来源项字段登记 `source_form_reason`（仅允许 `no_text_alternative`），用于记录确无文本替代、只能采用扫描图片/PDF 的 来源；校验通过后由 `inspect` 读取，不改提取与地址处理逻辑。
- 纯内部精简：`school_government_flow.py` 移除与核心层默认逻辑一致的 `inspect_source_file` 包装；`build_excel.py` 统一领域值构造并删除未使用的 `_main_common_rows`/`build_worksheet_rows` 别名。行为不变，全量测试通过。
- 配合核心库读取器修复：含 `<thead>` 表头的门户名录页表头行回插后可由 `inspect` 自动生成规则；配合核心库 zip 解压修复：GBK 中文附件名可读， 流程文档注明从下载清单 `extracted_files` 选取入选来源。
