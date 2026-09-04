# address 地址处理层

## 本层职责

把统一地址记录从「原始文本」处理到「规范化地址」，再经地图验证得到最终地址，
供各查询 Skill 复用；本层不依赖任何 Skill 的业务规则。

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `__init__.py` | 包标记。 |
| `amap_client.py` | 高德 API 客户端：滑动窗口限流、地理编码/POI/行政区查询、统一重试与错误归一。 |
| `city.py` | 城市标准化：按固定目录匹配城市名、查询直接下级行政区、构造/校验 `city_context`。 |
| `common.py` | 公共常量与记录规则：地址记录字段校验、行政区/具体位置拆分、同址比较键（`address_equivalence_key`）、地图匹配状态标签、地图处理结果记录构造。 |
| `normalize.py` | 地址规范化：清洗文本、城市归属判定（按城市目录排除外地城市）、下级行政区提取与核验、输出统一为「城市名 + 下级行政区 + 具体位置」。 |
| `process.py` | 批处理入口：规范化 → 逐条地图解析 → 汇总指标（状态计数、地图请求数、缺下级行政区数等）。 |
| `verify.py` | 地图验证：地理编码/POI 查询、地址组件比对（行政区、道路、门牌）、最终地址选择与地图补全。 |

## 修改记录

### 2026-09-04

- `common.py`、`normalize.py` 的省级前缀正则收窄：省级前缀内不再允许出现
  “省/市/县/区/旗/盟”字符，修复“广州市荔湾区省实路1号”等以“省X路”开头
  的道路被误判为外省冲突的问题；`tests/test_normalize_address.py` 增加
  “省实路”回归用例（53 项地址规范化测试通过）。

### 2026-09-03

- `common.py` 新增 `address_equivalence_key`：空白压缩、去 `中国`/省份
  前缀后按最后道路与门牌生成同址比较键；医疗与高校的本地重复实现删除，
  改为引用本函数。
- 由公共层根目录迁入 `city.py` 与 `amap_client.py`；地址层现在统一
  承载城市上下文、高德客户端与地址处理。

### 2026-09-03（地图决定状态机）

- `common.py` 新增地图状态 `needs_review`（展示为「部分匹配·待复核」）。
- `verify.py` 收敛最终地址决定：官网缺下级行政区时，只有地图结果与来源
  共享道路、门牌或地点锚点证据才允许补区；无法确证时保留官网原文并标记
  `needs_review`，不再采信无关 POI。「地图地址更详细即采用」同样受该
  确证门槛约束；`consistent` / `conflict` / POI 严格匹配语义保持不变。

### 2026-09-03（v2.1 加固）

- `normalize.py` 新增「城市简称 + 无后缀子区名」补全：空格分词写法
  “广州 花都 …”先补成“花都区”再输出规范地址，避免产生
  “广州市广州花都…”类重复城市前缀。
- `verify.py` 地理编码补区门槛收紧：缺下级行政区时只接受道路确证，或
  “门牌一致且地图地址自带道路”的确证；地图地址文本含公交站/地铁站/驿站等
  辅助 POI 字样时一律不采用为最终地址，落入 `needs_review` 保留官网原文。

### 2026-09-02

- `verify.py`
  - 移除 `SCHOOL_STAGE_SUFFIXES`、`school_type` 与学部后缀对应整套学校
    语义，公共层不再识别「小学部/初中部/高中部/中学部」；
    改为通用记录字段 `poi_name_aliases`：场景层提供完整候选名称后，
    公共层逐个名称做唯一 POI 匹配。基础教育技能的学部规则见其
    `school_common.py`。
- `common.py`、`normalize.py`、`verify.py`、`process.py`
  - 新增顶层 `address_mode` 三模式：`web_search`（名单约束城市 → 网页检索
    地址 → 地图处理）、`government_list`（政府名单可靠 → 规范补充 →
    地图兜底）、`map_search`（本轮 schema/占位，不执行检索）；
    `source_nature` 保留为来源证据，缺失 `address_mode` 时按来源推导。
  - 结构化有效地址（`normalization_status=complete` 且已解析到目标城市）
    直接采用来源地址，不再调用高德；`map_reason=地址有效，无需地图验证`。
  - `web_search` 完整有效地址不再做地理编码验证；不完整但有道路门牌仍走
    地理编码，空地址/无详细地址走严格 POI。
  - `government_list` 含道路门牌或具体地点的官方地址直接采用；
    空地址或仅区划地址走 POI 兜底；需要名称变体匹配时由记录
    `attributes.poi_name_aliases` 提供候选名称。
  - `map_search` 记录本轮固定 `skipped` 且不产出最终地址。
  - 指标新增 `address_mode_counts`。
- `verify.py`
  - POI 名称比较放宽：先按原有清洗全名精确比较，不等时再按容差基准比较；
    容差为移除括号内状态词（建设中/在建/拟建/筹设/筹办）并剥离名称开头的
    「城市名/区县/镇街」行政区前缀；城市与区县一致、地址唯一、辅助 POI
    排除等防错规则保持不变。
  - POI 兜底按 `address_mode` 分两档：`web_search` 只使用共同容差基线；
    `government_list` 的宽松匹配由 Skill 预生成的 `poi_name_aliases`
    提供，核心层不包含学部等场景规则。
  - 采用地图地址前删除括号内“地铁/公交/步行/交叉口/停车场”等交通引导
    文本，行政区、道路与门牌保持不变。
- `normalize.py`
  - 移除乱码修复与检测函数（`repair_mojibake_text`、`contains_encoding_corruption`），不再做乱码后处理。
  - `detect_city_prefix` 不再依赖传入省份，改为按城市目录识别任意城市全名/简称。
  - 新增外地城市排除：外地市全名无论有无区县均判 `conflict`；外地市简称 + 区县也判 `conflict`。
  - 下级行政区处理通用化：从 `city_context['subdivisions']` 推导该城市的下级后缀
    （区/县/市或街道/镇），统一提取并核验；不在列表的区县级候选判 `conflict`，
    街道/镇等低层级候选按缺失交给地图；规范化原因统一为「地址缺少下级行政区」。
- `process.py`
  - 移除编码相关指标；`missing_district_geocode_count` 更名为 `missing_admin_geocode_count`。
- `verify.py`
  - 移除「地址含编码替换字符，待重新抓取」的跳过分支；
    地图补全分支改为「缺下级行政区 → 地图补充下级行政区」。
  - `government_information` 分支新增具体地点词门控：
    官方地址无道路/门牌且不含小区、楼栋、村等具体地点词时，
    按学校名称走 POI 兜底（命中用地图地址、未命中保留官方地址）；
    含具体地点词的地址保持直接采用官方。
- `common.py`
  - 新增共享抽取后缀常量：`CITY_SUFFIXES`、`ADMIN_UNIT_SUFFIXES`、
    `SUB_LEVEL_SUFFIXES`、`PLACE_NAME_SUFFIXES`；
    `DISTRICT_LEVEL_SUFFIXES` 由 `ADMIN_UNIT_SUFFIXES - SUB_LEVEL_SUFFIXES` 推导，
    删除重复的 `LOWER_ADMIN_SUFFIXES`；`extract_address_components` 更名为
    `extract_admin_unit_components`。
- `normalize.py`、`verify.py`、`city.py`
  - 改用 `common.py` 的共享后缀常量，消除多文件重复定义；
    街道/镇等低层级后缀集合统一从 `common.py` 引入。
- `verify.py`
  - 术语与 `normalize.py` 统一：`district` 更名为 `admin_unit`，
    提示文案由「区县」统一为「下级行政区」；
    直辖市无省级上级（`province_name` 为 `None`）的模型保持不变。
  - 冗余清理：`resolve_poi_address` 的双名称查询改为循环；
    `build_source_components` 与 `address_detail_score` 共用
    `strip_city_prefix`；「地址缺少下级行政区」统一引用 `MISSING_ADMIN_REASON`。
- `common.py`
  - `extract_admin_unit_components` 改用全量 `ADMIN_UNIT_SUFFIXES` 提取，
    与 `normalize.py` 的下级行政区提取统一（东莞街道/镇、大理县级市等均能识别）；
    新增 `MISSING_ADMIN_REASON`、`strip_city_prefix`；
    删除无调用的 `validate_processed_address_record`。
  - 新增 `address_detail_key()`：提取最后道路与门牌号作为同址比较键，
    高校 Skill 的 `address_equivalence_key` 与地图同址去重改为共用该实现。
- `process.py`
  - 改为「逐条规范化后立即调用地图解析」，不再先统一规范化再统一查询高德，
    避免地图请求堆积；`resolve_address_payload` 校验逻辑保持不变。
- `normalize.py`
  - 修复「地点名称含异地城市校区」误判：先规范化官方地址，地址能在目标
    城市解析出有效结果时不再采用校区名中的异地城市简称结论；仅当地址为
    空或无法落到目标城市时才判 `conflict`。修复「东方校区」（广州天河
    东方二路/中山大道西）被误判为海南东方市的问题，并保留「江门校区 +
    空地址」等空地址场景的原有异地排除。

### 2026-09-03（v2.2 加固）

- `web/fetch_official_page.py`：行内标签识别支持“。通讯地址：”等标点边界后
  的标签与“X校区地址是…”句式，长描述后的“通讯地址/地址/校址”不再因前缀
  过长漏标。
- `verify.py`：
  - 规范化完整但只有行政区/街道/名称级文本（无道路、无门牌）的记录不再
    “直接采用跳过”，改走对应解析分支：`web_search` 用严格名称 POI 补齐，
    未命中时保留官网原文并置 `needs_review`（“部分匹配·待复核”）；纯区级
    且无地点文本的记录仍保持留空 `not_found`。
  - 新增 `has_verifiable_location`（排除仅有“街道”级词语且无门牌的情况），
    与 `has_location_detail_text` 一起决定“结构完整直接采用”与“待复核”门槛。
