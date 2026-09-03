# query-city-basic-education 基础教育检索 Skill

## 本层职责

按中国城市的直接下级行政单位检索政府公开的非高校学校名录，
提取学校与地址并生成区级和城市汇总 Excel。
由单个执行 Agent 按行政单位顺序检索与复核，固定处理统一调用
`scripts/` 下的脚本，不另写临时脚本复制逻辑。

## 目录结构

- `references/`：政府来源结果格式等参考文档。
- `scripts/`：固定处理脚本与来源读取器。
- `scripts/source_readers/`：HTML/Word/Excel/PDF/图片/视觉结果读取器。
- `scripts/tests/`：脚本测试。

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `SKILL.md` | 执行规范：行政单位任务划分、政府来源检索、提取计划复核、地址处理与工作簿生成。 |
| `requirements.txt` | 运行依赖。 |
| `references/government-source-format.md` | 政府来源结果与提取计划字段规范。 |
| `scripts/build_school_address.py` | 命令入口：`list-links` / `download` / `collect-details` / `inspect` / `extract`。 |
| `scripts/inspect_government_source.py` | 校验来源清单、识别文件/表格/列并生成待复核提取计划。 |
| `scripts/extract_school_records.py` | 按已复核规则从表格/CSS/键值表/正则提取学校与地址记录。 |
| `scripts/normalize_school_records.py` | 学校类型/办学性质规范化、校区地址拆分、按名称+地址去重。 |
| `scripts/build_excel.py` | 生成行政单位表与城市总表（学校信息表 + 各行政单位分表）。 |
| `scripts/source_readers/` | 按来源格式读取 HTML/Word/Excel/PDF 表格与图片/视觉结果。 |

## 修改记录

### 2026-09-02

- `scripts/normalize_school_records.py`、`scripts/extract_school_records.py`
  - 公共层 `verify.py` 中的学部后缀逻辑整体移回本技能：新增
    `SCHOOL_STAGE_SUFFIXES`、`build_poi_name_aliases()`，生成地址记录时
    为单学段记录写入通用 `attributes.poi_name_aliases`（如初中记录生成
    `初中部/中学部` 全名），核心层只按候选名称做唯一 POI 匹配。
  - 去重合并学校类型后同步重算 `poi_name_aliases`。
- `SKILL.md`
  - 输出目录层级统一为
    `output/<标准城市名>/<YYYY-MM-DD>/Basic_Education/<HHMMSS>/`，
    与高校的 `<YYYY-MM-DD>/Higher_Education/<HHMMSS>/` 对齐。
- `SKILL.md`
  - 输出目录增加 `<HHMMSS>` 运行层，每次调用独立、不覆盖同日早前结果，
    与高校 Skill 的目录模式对齐。
- `scripts/build_excel.py`
  - 最终列顺序与实现对齐（发布日期在地址列之前）；
  - 日期单元格与原子保存改用公共层（`format_date_cell`、
    `write_workbook_atomically`）。
- `scripts/collect_linked_html.py`
  - manifest 改用公共原子写；适配 `fetch_direct_content` 5 元组返回。
- `scripts/inspect_government_source.py`、`extract_school_records.py`、
  `build_school_address.py`
  - JSON 读写改用公共 `query_city_core.io_utils`，
    删除本地 `read_json_object` / `write_json_object`（写改为原子）。
- `scripts/extract_school_records.py`
  - 本地 `format_source_reference` 更名为 `build_source_reference`，
    与公共层 `excel_style.format_source_reference`（展示解析）区分职责。
  - 三处「校区拆分 + 逐地点生成记录」循环合并为
    `build_records_for_locations` 共用。
- `scripts/inspect_government_source.py`
  - `inspect_source_file` 只计算一次来源格式，供表格与重复容器分支复用。
- `scripts/normalize_school_records.py`、`scripts/build_excel.py`
  - 学校类型合并逻辑收敛为 `normalize_school_records.merge_school_types`，
    `build_excel` 改为引用，删除本地重复实现；
  - `build_excel` 的行政单位结果读取改用公共 `read_json_payload`。
  - 新增 `SCHOOL_TYPE_STAGES` 与 `school_type_stages`：完全中学、九年/
    十二年/十五年一贯制学校按覆盖学段去重合并，保留官方类型标签
    （如「小学 + 九年一贯制学校 → 九年一贯制学校」）。
  - 公共层 `verify.py` 政府分支补齐「地址不完整 → 地图兜底」：
    只有区/街道/片区且无具体地点词的官方地址按学校名称走 POI 补全，
    命中用地图地址、未命中保留官方；有小区/楼栋/村等具体信息的地址直接采用官方。
- `SKILL.md`、`references/government-source-format.md`
  - 明确一贯制/完中按覆盖学段计入四类必查覆盖（完全中学=初中+高中，
    九年=小学+初中，十二年=小学+初中+高中，十五年=幼儿园+小学+初中+高中）；
  - 细化地图兜底门控描述、合并按学段去重说明、collect-details 错误复核
    与空地址留痕要求。
- `scripts/build_school_address.py`
  - collect-details 失败时在 stderr 打印下载错误条数，提示复核清单 `errors`。
- `scripts/build_excel.py`
  - 各行政单位工作簿新增「异常校」工作表：汇总该行政单位最终地址为空的
    学校及异常原因（序号、行政单位、学校名称、学校类型、办学性质、
    异常原因、地图匹配状态、信息来源、发布日期）；城市总表不包含异常校。
- `scripts/source_readers/`
  - 删除 `common.py`：`normalize_text` 保留在
    `source_readers/__init__.py`（基础教育专用，不放入公共层）；
    单元格与 DataFrame 转换归入新增的 `tables.py`。
  - 来源格式支持 `.xlsm` 与 `.csv`；CSV 按 UTF-8 优先、GB18030 兜底读取，
    并作为单一 `sheet` 表格参与检查与提取；
  - `load_source_html` 的 HTML 读取器别名简化为 `load_html_document`，
    并在 `__init__.py` 说明 `normalize_text` 先于读取器导入的原因。
- `scripts/build_school_address.py`
  - 新增 `list-links`、`download` 子命令：栏目页候选链接抓取与来源文件
    批量下载，实现下沉到公共层
    `query_city_core.directory_links` / `query_city_core.source_files`，
    skill 只保留命令入口，供后续政府建筑、医院建筑等来源检索复用。
- `scripts/inspect_government_source.py`
  - 来源只覆盖单一学校类型且表格无类型列时，自动预填固定学校类型
    （如幼儿园、小学、初级中学、职业中学、特殊教育学校）；
  - 办学性质列存在空单元格时，自动把该列加入向下填充建议，
    Agent 复核后仍须人工设 `approved = true`。
- `SKILL.md`、`references/government-source-format.md`
  - 补充栏目页 `list-links` 与来源下载 `download` 的使用流程与清单格式
    （`directory_link_manifest`、`source_download_manifest`）。
- `scripts/normalize_school_records.py`
  - 校区地址按 `/` 分段兜底：整行斜杠校区中部分段无法识别时，已识别
    段照常拆分为独立校区记录，无法识别段单独保留为一条原始记录，
    不再整行回退为单条（修复龙口西小学四校区地址合并问题）；
    不含校区标签的斜杠地址仍整体保留，不按斜杠拆分。
- `SKILL.md`、`references/government-source-format.md`、`requirements.txt`
  - 执行边界表把 `list-links` 标为可选，并给出目录页清单与结果文件的
    完整格式示例（`directory_link_manifest`/`directory_links`）；
  - 明确九年一贯制、完全中学、十二年一贯制等多学段覆盖来源无类型列时，
    固定学校类型由 Agent 复核时人工填写；
  - 网络访问措辞与脚本能力对齐：`download`/`collect-details`/`list-links`
    内置公共直连兜底（urllib → curl），浏览器仅用于需执行脚本或登录的页面；
  - requirements 口径澄清：只锁定 `query-city-core`，其余脚本依赖
    按 SKILL「输入与运行条件」安装。
- `scripts/build_school_address.py`
  - `collect-details` 实现下沉到公共层 `query_city_core.linked_pages`，
    删除 `scripts/collect_linked_html.py`，命令入口保持不变；
  - `download` 清单支持可选 `allowed_domain`（公共层
    `source_files` 按最终地址域名校验）。
- `scripts/tests/test_build_excel.py`
  - 测试文案统一为「下级行政区」，删除残留的「区县」旧词。
- `SKILL.md`、`references/`
  - 回退行政单位分派方案：删除 `agent-dispatch.md` 派发模板与
    `fork_turns="none"` 约束，SKILL 恢复由单个执行
    Agent 按行政单位顺序执行；地址处理仍由同一执行 Agent
    串行调用 `address.process`。
- `SKILL.md`
  - 下载/链接抓取默认同主机串行（间隔 0.3 秒），三个命令支持
    `--max-workers`、`--host-max-workers`、`--host-min-interval`；
  - 地图阶段串行执行（同一时间只允许一个
    `address.process` 进程），并注明当前高德 key 每秒上限少于 3 次、
    公共层按 1 秒窗口 2 次执行、两个行政单位并行即可能超限。
- `scripts/build_school_address.py`
  - `list-links`/`download` 分支补上指标输出与提前返回，避免落入
    extract 分支；`download`/`list-links`/`collect-details` 透传
    并发与同域节流参数（公共层 `query_city_core.host_gate`）。
