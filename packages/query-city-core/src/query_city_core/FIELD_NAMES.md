# 公共接口字段名

本文件只登记 `query_city_core` 跨模块传递的通用字段。场景专属字段
（学校类型、机构级别、主管部门等）属于 Skill 的 `attributes`，由各
Skill references 自行登记，公共层不解释、不校验其 key。

## 城市上下文

由 `query_city_core.address.city` 生成，供地址处理及各类城市查询 Skill
使用。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `stage` | string | 固定为 `city_context`。 |
| `input_city` | string | 去除首尾空白后的用户原始输入。 |
| `city_name` | string | 城市目录标准化后的地级单位或直辖市名称。 |
| `province_name` | string \| null | 非直辖市的上级省级单位；直辖市为 `null`。 |
| `subdivisions` | array | 高德返回并整理后的直接下级行政单位列表。 |

`subdivisions` 每项包含 `name`、`adcode`、`level`。

## 公共地址记录

`address_records`、`processed_address_records` 顶层均携带 `city_context`。

每条记录固定字段：

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `place_name` | string | 用于名称比对的地点名称。 |
| `original_address` | string | 来源原始地址；允许为空字符串。 |
| `address_mode` | string | `government_list`、`web_search` 或 `map_search`。 |
| `source_nature` | string | `government_information`、`web_search` 或 `map_search`，只作来源证据。 |
| `source_reference` | string | 取得该地址/地点线索的来源定位。 |
| `source_date` | string | 可选；来源发布日期或数据截止日期，格式 `YYYY-MM-DD`。 |
| `attributes` | object | 不透明业务对象。核心只读取 `administrative_unit` 作为通用地理约束。 |

地址处理输出在保留输入字段基础上固定增加：

| 字段名 | 说明 |
| --- | --- |
| `normalized_address` | 规范化地址。 |
| `normalization_status` | `complete`、`partial`、`empty`、`invalid` 或 `conflict`。 |
| `resolved_city` | 地址实际归属城市。 |
| `map_address` | 高德返回并规范化的地址。 |
| `map_match_status` | `skipped`、`consistent`、`partial`、`conflict`、`poi_match`、`not_found`、`ambiguous` 或 `error`。 |
| `map_reason` | 地图查询/比较/跳过原因。 |
| `final_address` | 最终采用地址；无法确认时为空。 |
| `final_address_source` | `official` 或 `map`。 |
| `final_address_reason` | 最终选择原因。 |

## 来源证据

页面/附件访问可附带 `access_attempts` 数组；每项含 `method`、`url`、
`final_url`、`http_status`、`success`、`error`、`elapsed_ms`。

## 统一工作簿输出列

主表固定列顺序：

```text
序号 | [Skill 领域列…] | 查询日期 | 地址 | 地址获取方式 | 地图匹配状态 | 信息来源
```

异常表固定列顺序：

```text
序号 | [Skill 领域列…] | 异常原因 | 信息来源 | 查询日期
```

查询日期默认使用运行日 `YYYY-MM-DD`。来源日期等只作为 Skill 可选领域列。

## 官方提取规则

公共提取规则只使用中性字段：

| 字段 | 说明 |
| --- | --- |
| `place_name_columns/labels/selector` | 地点名称定位。 |
| `original_address_column/labels/selector` | 原始地址定位。 |
| `attribute_fields` | 场景属性定位数组；每项含 `field`、`column/value/selector/labels`。 |

`field` 名称由场景层提供，公共层不登记具体业务字段。
