# address 地址处理层

## 本层职责

把统一地址记录从「原始文本」处理到「规范化地址」，再经地图验证得到最终地址，
供各查询 Skill 复用；本层不依赖任何 Skill 的业务规则。

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `__init__.py` | 包标记。 |
| `common.py` | 公共常量与记录规则：地址记录字段校验、行政区/具体位置拆分、地图匹配状态标签、地图处理结果记录构造。 |
| `normalize.py` | 地址规范化：清洗文本、城市归属判定（按城市目录排除外地城市）、下级行政区提取与核验、输出统一为「城市名 + 下级行政区 + 具体位置」。 |
| `process.py` | 批处理入口：规范化 → 逐条地图解析 → 汇总指标（状态计数、地图请求数、缺下级行政区数等）。 |
| `verify.py` | 地图验证：地理编码/POI 查询、地址组件比对（行政区、道路、门牌）、最终地址选择与地图补全。 |

## 修改记录

### 2026-09-02

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
