# 统一地址处理结构设计

## 文档状态

本文记录统一地址结构和分支路由的确认结论。地址规范化、地图校验、地图兜底和最终地址路由已经按本文实现；场景前置处理和最终 Excel 仍由各场景单独拼接。

## 总体路线

所有场景最开始只要求输入标准城市名称。场景自己的前置步骤负责搜索网页、解析页面、读取 Excel 或提取 PDF，并生成能够进入公共地址处理的记录。

```text
城市名称
  → 场景前置处理
  → 地点 + 原始地址 + 来源信息 + 动态业务字段
  → 地址规范化
  → 按来源性质和规范化结果选择地图路线
  → 最终地址
  → 场景自己的 Excel 输出
```

高校场景中的`prepare_universities.py`属于前置处理。它产生学校名称、学校标识码、办学层次等高校字段；其它场景可以产生不同字段。公共地址组件只读取固定地址字段，并原样传递动态业务字段。

公共代码位于`.dsh/components`：

- `normalize_city.py`使用固定城市资产转换标准城市名称，并通过高德返回直接下级行政单位；
- `normalize_address.py`只执行统一输入校验和地址规范化；
- `verify_address.py`只验证完整规范地址，不决定最终地址；
- `fallback_address.py`只在上层允许时执行严格 POI 兜底；
- `process_addresses.py`是无 ID 的公共编排入口，输入阶段固定为`address_records`，输出阶段固定为`processed_address_records`。

`process_addresses.py`命令行只保留`--input`和`--output`，地图密钥通过公共`env_utils.py`从进程环境或工作区`.env`读取。

## 公共字段与变量命名

公共 JSON 字段和 Python 变量统一使用英文`snake_case`。公共层固定字段不得由场景脚本改名；`attributes`中的业务字段由各场景定义，但同一场景必须使用一套稳定英文键，中文列名只在最终 Excel 输出时映射。

### 批次字段

| JSON字段 | Python变量 | 所在阶段 | 含义 |
| --- | --- | --- | --- |
| `schema_version` | `schema_version` | 输入、输出 | 公共结构版本 |
| `stage` | `stage` | 输入、输出 | 输入为`address_records`，输出为`processed_address_records` |
| `city` | `city` | 输入、输出 | 本批次标准城市名称 |
| `items` | `address_records` | 输入 | 待处理的单地点记录集合 |
| `items` | `processed_records` | 输出 | 完成公共处理的单地点记录集合 |
| `metrics` | `metrics` | 输出 | 状态计数和地图请求统计 |

### 单地点固定字段

| JSON字段 | Python变量 | 产生阶段 | 含义 |
| --- | --- | --- | --- |
| `place_name` | `place_name` | 场景前置层 | 可供地图检索的完整地点名称 |
| `original_address` | `original_address` | 场景前置层 | 检索或文件提取得到的地址原文，允许为空 |
| `source_nature` | `source_nature` | 场景前置层 | `web_search`或`government_information` |
| `source_reference` | `source_reference` | 场景前置层 | 网页或文件中的可定位来源依据 |
| `attributes` | `attributes` | 场景前置层 | 公共组件不解释的场景业务字段 |
| `normalized_address` | `normalized_address` | 地址规范化 | 规范化后的目标城市地址 |
| `normalization_status` | `normalization_status` | 地址规范化 | `empty`、`complete`、`partial`、`invalid`或`conflict` |
| `normalization_reason` | `normalization_reason` | 地址规范化 | 规范化结果原因 |
| `map_address` | `map_address` | 地图验证或兜底 | 地图返回并保留的地址 |
| `map_status` | `map_status` | 地图验证或兜底 | 地图中间状态 |
| `map_reason` | `map_reason` | 地图验证或兜底 | 地图状态原因 |
| `map_poi_type` | `map_poi_type` | 地图验证或兜底 | 高德原生POI类型 |
| `map_poi_typecode` | `map_poi_typecode` | 地图验证或兜底 | 高德原生POI分类编码 |
| `final_address` | `final_address` | 公共路由 | 最终输出地址 |

公共代码中的单条输入统一称为`address_record`，完成处理的单条结果称为`processed_record`；地图候选集合称为`map_candidates`，单个候选称为`map_candidate`；地图请求累计数量称为`map_request_count`。公共流程不增加`id`或`parent_id`。

## 通用输入

### 批次输入

| 字段 | 是否必需 | 含义 |
| --- | --- | --- |
| `city` | 是 | 本次处理的标准城市名称 |

### 预处理后每条记录

| 字段 | 是否必需 | 含义 |
| --- | --- | --- |
| `place_name` | 是 | 可识别、可供地图检索的地点名称，例如学校、校区、分院或分支机构 |
| `original_address` | 字段必需，值可为空 | 前置检索或文件提取得到的地址原文 |
| `source_nature` | 是 | 来源性质，当前固定为`web_search`或`government_information` |
| `source_reference` | 是 | 支持该记录的网页 URL，或文件名、工作表、行号、PDF页码等定位信息 |
| `attributes` | 否 | 场景动态业务字段，公共组件原样传递，不解释其内容 |

`original_address = ""`表示前置处理没有取得任何地址文本。它与地址文本存在但规范化结果不完整、无效或冲突是不同状态。

### `place_name`生成规则

`place_name`使用“主体名称 + 明确地点名称”的完整可检索名称：

- 有明确校区、分院或分支名称时，将其与主体名称拼接，例如`暨南大学` + `石牌校区` → `暨南大学石牌校区`；
- 没有明确地点名称时，直接使用主体名称；
- 地点名称已经包含主体全名时直接使用，不重复拼接；
- 不根据地址地名推断或编造校区、分院和分支名称。

主体名称和地点名称仍分别保存在`attributes`的场景业务字段中，`place_name`只作为公共地图检索字段。

### 多地点拆分规则

前置阶段识别出同一主体下的多个明确校区、分院或分支时，必须直接拆成多条记录。每条记录只对应一个`place_name`，并分别保存该地点的`original_address`和`source_reference`。

后续地址规范化、地图验证和地图兜底均按单条地点记录处理，不负责把一个主体记录再次展开为多个地点。只有前置阶段完全没有识别出具体地点名称时，才使用主体名称作为唯一的`place_name`。

## 通用派生字段

| 字段 | 含义 |
| --- | --- |
| `normalized_address` | 规范化后的“市 + 区县 + 具体位置”地址 |
| `normalization_status` | 地址规范化状态 |
| `normalization_reason` | 规范化未完成时的具体原因 |
| `map_address` | 地图验证或地图兜底取得的地址；未调用地图时为空 |
| `map_status` | 地图验证或兜底的中间状态，不要求写入最终 Excel |
| `map_reason` | 地图状态的具体原因 |
| `map_poi_type` | 地图 API 返回的 POI 类型，仅用于候选判断和追溯 |
| `map_poi_typecode` | 地图 API 返回的 POI 分类编码，仅用于候选判断和追溯 |
| `final_address` | 最终输出地址 |

`map_status`使用`consistent`、`partial`、`conflict`、`not_found`、`fallback`、`ambiguous`、`error`和`skipped`。其中前三项用于地址验证，`fallback`表示唯一合格 POI 已被采用，`skipped`表示按来源路由禁止或无需调用地图。

建议最终 Excel 的固定地址列仍使用：`原始地址`、`规范地址`、`地图地址`、`最终地址`、`来源性质`、`来源依据`。场景业务列由`attributes`决定。

## 规范化状态

`normalization_status`固定使用以下值：

| 状态 | 定义 |
| --- | --- |
| `empty` | `original_address`原本就是空值，前置处理没有取得地址文本 |
| `complete` | 地址属于目标城市，并且包含可用的具体位置 |
| `partial` | 地址属于目标城市，但只到区县、乡镇等位置，具体程度不足 |
| `invalid` | 原始文本非空，但清理后不是可用地址 |
| `conflict` | 原始文本明确指向目标城市以外的城市 |

`empty`与其余状态必须根据原始输入区分，不能把规范化失败统一改写成`empty`。

## 来源路由

### `web_search`

1. `original_address`非空且规范化完整：
   - 调用地图进行交叉验证；
   - 地图地址单独保存；
   - 无论地图结果为一致、部分一致、冲突、未找到或服务失败，`final_address`都采用`normalized_address`；
   - 地图冲突或异常写入中间状态和查询日志，不用地图覆盖官网规范地址。
2. `original_address`为空且`place_name`非空：
   - 允许按地点名称调用地图兜底；
   - 只有合格地图候选才能成为`map_address`和`final_address`。
3. `original_address`非空，但规范化结果为不完整、无效或明确指向其他城市：
   - 不允许进入地图兜底；
   - `final_address`留空并记录原因。

### `government_information`

1. `original_address`非空且规范化完整：
   - 不调用地图验证；
   - 不调用地图兜底；
   - `map_address`留空；
   - `final_address = normalized_address`。
2. 规范化结果不完整且`place_name`非空：
   - 允许调用地图兜底；
   - 是否接受地图候选仍需遵守地点身份和候选唯一性规则。

政府信息的地图路由固定为：

| 规范化状态 | 有`place_name`时的处理 |
| --- | --- |
| `complete` | 直接使用规范地址，禁止调用地图 |
| `empty` | 允许地图兜底 |
| `partial` | 允许地图兜底 |
| `invalid` | 不允许地图兜底 |
| `conflict` | 不允许地图兜底 |

脚本读取到`source_nature = government_information`且已有完整规范地址时，必须在发起地图 API 请求前结束地图分支。

## 地图兜底候选规则

地图兜底按一条地点记录查询，并且最多产生一个地图地址：

1. 对`place_name`和地图 POI 名称只做无语义格式清理，包括移除空白、统一或忽略中英文括号和连接符；
2. 清理后的名称必须完全一致，禁止使用包含关系、模糊相似度或自动别名匹配；
3. 不提供`place_aliases`，地图名称不一致时不因地址相同而改用别名候选；
4. 地图返回城市必须与批次`city`一致；
5. 地图返回地址必须能够规范化为`complete`；
6. 使用高德 API 原生返回的`type`和`typecode`排除公交站、地铁站、出入口、停车场等明显附属设施；
7. 不要求前置步骤提供`map_type_keywords`，也不在公共请求中按具体行业硬编码 POI 类型；
8. 多个候选归一到同一个地址时可以去重；存在多个不同地址时标记候选不唯一，`final_address`留空；
9. 公共地图阶段不把一条地点记录展开成多条记录。

`map_poi_type`和`map_poi_typecode`属于中间追溯字段，不要求写入最终 Excel。

## 建议记录结构

```json
{
  "schema_version": "1.0",
  "stage": "address_records",
  "city": "广州市",
  "items": [
    {
      "place_name": "暨南大学石牌校区",
      "original_address": "天河区黄埔大道西601号",
      "source_nature": "web_search",
      "source_reference": "https://example.edu.cn/contact",
      "attributes": {
        "school_name": "暨南大学",
        "campus_name": "石牌校区",
        "school_identifier": "4144010559",
        "education_level": "本科"
      },
      "normalized_address": "",
      "normalization_status": "",
      "normalization_reason": "",
      "map_address": "",
      "map_status": "",
      "map_reason": "",
      "map_poi_type": "",
      "map_poi_typecode": "",
      "final_address": ""
    }
  ]
}
```

固定字段和场景业务字段均使用稳定英文键，中文列名只在最终 Excel 输出时映射。公共流程不引入`id`、`parent_id`或其它额外标识字段；前置阶段拆分完成的单地点记录按原顺序向后传递。

## 当前结论

统一结构、规范化状态、来源路由、多地点拆分和地图兜底候选规则已经实现为公共代码。后续发现具体场景无法覆盖时，再用实际案例修正规则，不预先增加别名或行业专属字段。
