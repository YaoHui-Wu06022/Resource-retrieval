#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按地址或地点名称查询高德，并确定最终规范地址。"""

import re

from ..amap_client import (
    fetch_amap_geocodes,
    fetch_amap_pois,
    normalize_amap_value,
)
from .common import (
    MISSING_ADMIN_REASON,
    PLACE_NAME_SUFFIXES,
    build_map_result_record,
    compact_address,
    extract_admin_unit_components,
    strip_city_prefix,
)
from .normalize import normalize_address_value


ROAD_PATTERN = re.compile(
    r'([\u4e00-\u9fffA-Za-z0-9·\-]{1,30}?(?:大道|公路|街道|胡同|路|街|巷|道)[东南西北中]?)'
)
NUMBER_PATTERN = re.compile(
    r'([0-9A-Za-z一二三四五六七八九十百千万甲乙丙丁\-之]+号(?:院)?)'
)
DISTINCTIVE_ANCHOR_PATTERN = re.compile(
    r'大学城|职教园|大学园|高教园区|高校园区|教育园区|科教城'
)
NAMED_PLACE_PATTERN = re.compile(
    r'([\u4e00-\u9fffA-Za-z0-9·\-]{1,20}(?:'
    + '|'.join(PLACE_NAME_SUFFIXES)
    + r'))'
)
ADMIN_SUFFIX_PATTERN = re.compile(
    r'(?:特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|自治州|地区|盟|省|市|区|县|旗)$'
)
MUNICIPALITIES = {'北京市', '天津市', '上海市', '重庆市'}
STATUS_PRIORITY = {'consistent': 0, 'partial': 1, 'conflict': 2}
AUXILIARY_POI_PATTERN = re.compile(
    r'公交车站|地铁站|停车场|出入口|通行设施|收费站|服务区'
)
NAME_FORMAT_PATTERN = re.compile(r'[\s()（）\[\]【】{}《》<>·\-—–_]')
CAMPUS_NEW_MODIFIER_PATTERN = re.compile(r'新(?=校区|校园)')
GOVERNMENT_SPECIFIC_LOCATION_PATTERN = re.compile(
    r'小区|花园|花苑|苑|新村|社区|村|里|路|街|巷|大道|公路|弄|段|号|栋|座|楼|'
    r'园|校区|院区|工业区|产业园'
)


def normalize_admin_name(value):
    """移除行政区名称末尾的层级后缀。"""
    return ADMIN_SUFFIX_PATTERN.sub('', compact_address(value))


def normalize_road_name(value):
    """统一道路名称中的空白和标点。"""
    return compact_address(value)


def classify_road_relation(source_road, map_road):
    """区分道路名称完全一致、有限变体和明确冲突。"""
    source_name = normalize_road_name(source_road)
    map_name = normalize_road_name(map_road)
    if source_name == map_name:
        return 'equal'
    source_base = re.sub(r'(?:辅路|[东南西北中])$', '', source_name)
    map_base = re.sub(r'(?:辅路|[东南西北中])$', '', map_name)
    if source_base == map_base:
        return 'partial'
    if source_name.endswith(map_name) or map_name.endswith(source_name):
        return 'suffix'
    return 'conflict'


def normalize_house_number(value):
    """统一门牌号后缀后用于精确比较。"""
    return re.sub(r'(?:号院|号|院)$', '', compact_address(value))


def extract_road_name(value):
    """从具体位置文本中提取最后一个明确道路名称。"""
    matches = list(ROAD_PATTERN.finditer(compact_address(value)))
    return matches[-1].group(1) if matches else ''


def extract_house_number(value):
    """从具体位置文本中提取明确门牌号。"""
    match = NUMBER_PATTERN.search(compact_address(value))
    return match.group(1) if match else ''


def extract_location_anchors(value):
    """提取园区类锚点和带名称的地点锚点。"""
    text = compact_address(value)
    anchors = [match.group(0) for match in DISTINCTIVE_ANCHOR_PATTERN.finditer(text)]
    number_matches = list(NUMBER_PATTERN.finditer(text))
    place_scope = text[number_matches[-1].end():] if number_matches else text
    place_match = NAMED_PLACE_PATTERN.search(place_scope)
    if place_match:
        anchors.append(place_match.group(1))
    return list(dict.fromkeys(anchors))


def build_source_components(address_record, city):
    """从规范地址构造明确存在的比较组件。"""
    normalized_address = str(
        address_record.get('normalized_address') or ''
    ).strip()
    detail = strip_city_prefix(normalized_address, city)
    admin_unit, location = extract_admin_unit_components(detail)
    return {
        'province': '',
        'city': city,
        'admin_unit': admin_unit,
        'detail': location,
        'road': extract_road_name(location),
        'number': extract_house_number(location),
        'anchors': extract_location_anchors(location),
    }


def extract_map_address_detail(address, values):
    """从地图完整地址开头移除已返回的行政区组件。"""
    remaining = compact_address(address)
    for value in values:
        normalized_value = compact_address(value)
        if normalized_value and remaining.startswith(normalized_value):
            remaining = remaining[len(normalized_value):]
    return remaining


def build_map_components(map_candidate, source_components):
    """把高德候选转换为稳定的地图地址组件。"""
    address = normalize_amap_value(map_candidate.get('formatted_address'))
    province = normalize_amap_value(map_candidate.get('province'))
    city = normalize_amap_value(map_candidate.get('city'))
    admin_unit = normalize_amap_value(map_candidate.get('district'))
    if not city and source_components.get('city') in MUNICIPALITIES:
        city = province
    detail = extract_map_address_detail(address, (province, city, admin_unit))
    return {
        'province': province,
        'city': city,
        'admin_unit': admin_unit,
        'street': normalize_amap_value(
            map_candidate.get('street')
        ) or extract_road_name(detail),
        'number': normalize_amap_value(
            map_candidate.get('number')
        ) or extract_house_number(detail),
        'address': address,
    }


def compare_admin_components(source, map_components):
    """比较双方明确提供的城市和下级行政区并返回缺失信息。"""
    missing = []
    labels = {'city': '城市', 'admin_unit': '下级行政区'}
    for field in ('city', 'admin_unit'):
        source_value = str(source.get(field) or '')
        map_value = str(map_components.get(field) or '')
        if source_value and map_value:
            if normalize_admin_name(source_value) != normalize_admin_name(map_value):
                return f'{labels[field]}冲突：规范地址“{source_value}”，地图“{map_value}”', []
        elif source_value:
            missing.append(f'地图{labels[field]}')
    return '', missing


def has_matching_anchor(anchors, map_address):
    """判断地图地址是否包含来源材料明确给出的地点锚点。"""
    map_text = compact_address(map_address)
    return any(compact_address(anchor) in map_text for anchor in anchors)


def judge_address_match(source_address, source, map_components):
    """按显式地址组件和地点锚点判定地图候选。"""
    conflict_reason, missing = compare_admin_components(source, map_components)
    if conflict_reason:
        return 'conflict', conflict_reason

    source_road = source.get('road') or ''
    map_road = map_components.get('street') or ''
    road_matches = False
    if source_road and map_road:
        road_relation = classify_road_relation(source_road, map_road)
        if road_relation == 'conflict':
            return 'conflict', f'道路冲突：规范地址“{source_road}”，地图“{map_road}”'
        if road_relation == 'suffix':
            missing.append('道路简称')
        if road_relation == 'partial':
            missing.append('道路方位或辅路信息不完整')
        else:
            road_matches = True
    elif source_road:
        missing.append('地图道路')

    source_number = source.get('number') or ''
    map_number = map_components.get('number') or ''
    if source_number and map_number:
        if normalize_house_number(source_number) != normalize_house_number(map_number):
            return 'conflict', f'门牌号冲突：规范地址“{source_number}”，地图“{map_number}”'
    elif source_number:
        missing.append('地图门牌号')

    if missing:
        if missing == ['道路简称'] and source_number and map_number:
            return 'partial', f'道路简称：规范地址“{source_road}”，地图“{map_road}”'
        return 'partial', '无明确冲突，但以下规范地址组件未获地图支持：' + '、'.join(missing)
    map_address = map_components.get('address') or ''
    if compact_address(source_address) == compact_address(map_address):
        return 'consistent', '规范地址与地图地址文本完全相同'
    if road_matches:
        if source_number:
            return 'consistent', '行政区、道路和门牌号均一致'
        return 'consistent', '行政区和道路一致；地图新增门牌号不改变规范地址'
    if has_matching_anchor(source.get('anchors') or [], map_address):
        return 'consistent', '行政区和地点锚点一致'
    return 'partial', '无明确冲突，但缺少可确认一致的道路、门牌号或地点锚点'


def choose_map_result(address_record, city, map_candidates):
    """从高德候选中选择验证状态最可靠的一条。"""
    source_address = str(
        address_record.get('normalized_address') or ''
    ).strip()
    source_components = build_source_components(address_record, city)
    judged_candidates = []
    for map_candidate in map_candidates:
        map_components = build_map_components(map_candidate, source_components)
        map_match_status, map_reason = judge_address_match(
            source_address, source_components, map_components
        )
        judged_candidates.append({
            'map_address': map_components['address'],
            'map_match_status': map_match_status,
            'map_reason': map_reason,
            'map_poi_type': '',
            'map_poi_typecode': '',
        })
    if not judged_candidates:
        return None
    return min(
        judged_candidates,
        key=lambda map_candidate: STATUS_PRIORITY[map_candidate['map_match_status']],
    )


def normalize_map_address(address, city_context, target_administrative_unit=''):
    """将高德返回地址整理为与来源地址相同的规范前缀形式。"""
    normalized = normalize_address_value(
        address,
        city_context,
        target_administrative_unit,
    )
    return normalized['normalized_address'] if normalized[
        'normalization_status'
    ] in {'complete', 'partial'} else ''


def address_detail_score(address, city):
    """按道路、门牌和剩余位置文本衡量地址的具体程度。"""
    normalized_address = compact_address(address)
    detail = strip_city_prefix(normalized_address, city)
    _, location = extract_admin_unit_components(detail)
    return (
        bool(extract_road_name(location)),
        bool(extract_house_number(location)),
        len(location),
    )


def has_detailed_address(address_record, city):
    """判断来源文本是否已提供道路或门牌等实际地址信息。"""
    source_components = build_source_components(address_record, city)
    return bool(source_components['road'] or source_components['number'])


def has_government_specific_location(address_record, city):
    """判断政府资料地址是否已给出小区、楼栋等具体地点。"""
    source_components = build_source_components(address_record, city)
    return bool(
        GOVERNMENT_SPECIFIC_LOCATION_PATTERN.search(
            source_components['detail']
        )
    )


def choose_final_address(address_record, map_result, city):
    """在不冲突的前提下保留道路、门牌等信息更完整的一方。"""
    official_address = str(address_record.get('normalized_address') or '').strip()
    map_address = str(map_result.get('map_address') or '').strip()
    map_match_status = map_result.get('map_match_status')
    if not map_address:
        return official_address, 'official', '地图未提供可用地址'
    if map_match_status == 'conflict':
        return official_address, 'official', '地址组件冲突，保留来源地址'
    if address_detail_score(map_address, city) > address_detail_score(
        official_address, city
    ):
        return map_address, 'map', '地图地址更详细'
    return official_address, 'official', '来源地址不比地图地址简略'


def verify_map_address(
    address_record,
    city_context,
    api_key,
    rate_limiter,
    fetch_geocodes=fetch_amap_geocodes,
):
    """按完整来源地址查询地理编码并比较地址组件。"""
    processed_record = build_map_result_record(address_record)
    if not api_key:
        processed_record.update(map_match_status='error', map_reason='未配置 AMAP_KEY')
        return processed_record, 0
    map_candidates, error_reason = fetch_geocodes(
        address_record['normalized_address'],
        city_context['city_name'],
        api_key,
        rate_limiter,
    )
    if error_reason:
        processed_record.update(map_match_status='error', map_reason=error_reason)
        return processed_record, 1
    selected_candidate = choose_map_result(
        address_record, city_context['city_name'], map_candidates
    )
    if not selected_candidate:
        processed_record.update(
            map_match_status='not_found',
            map_reason='高德服务正常但未找到结果',
        )
        return processed_record, 1
    selected_candidate['map_address'] = normalize_map_address(
        selected_candidate['map_address'],
        city_context,
        (address_record.get('attributes') or {}).get('administrative_unit'),
    )
    processed_record.update(selected_candidate)
    return processed_record, 1


def normalize_place_name(value):
    """移除地点名称中不影响身份的空白、括号和连接符。"""
    return NAME_FORMAT_PATTERN.sub('', str(value or '')).strip()


def normalize_campus_name_for_match(value):
    """比较地点名称时忽略校区核心词前直接修饰的“新”字。"""
    return CAMPUS_NEW_MODIFIER_PATTERN.sub('', normalize_place_name(value))


def build_poi_address(poi, city_context, target_administrative_unit=''):
    """将 POI 的下级行政区和详细地址整理为规范地址。"""
    admin_unit = normalize_amap_value(poi.get('adname'))
    detail = normalize_amap_value(poi.get('address'))
    city = city_context['city_name']
    if not detail:
        return ''
    if detail.startswith(city):
        raw_address = detail
    elif admin_unit and detail.startswith(admin_unit):
        raw_address = f'{city}{detail}'
    else:
        raw_address = f'{city}{admin_unit}{detail}'
    return normalize_map_address(
        raw_address,
        city_context,
        target_administrative_unit,
    )


def build_poi_candidate(
    place_name,
    city_context,
    poi,
    target_administrative_unit='',
):
    """筛选名称、城市和地址均可确认的 POI 候选。"""
    poi_name = normalize_amap_value(poi.get('name'))
    if normalize_campus_name_for_match(
        place_name
    ) != normalize_campus_name_for_match(poi_name):
        return None
    if normalize_place_name(normalize_amap_value(poi.get('cityname'))) != (
        normalize_place_name(city_context['city_name'])
    ):
        return None
    if target_administrative_unit and normalize_place_name(
        normalize_amap_value(poi.get('adname'))
    ) != normalize_place_name(target_administrative_unit):
        return None
    if AUXILIARY_POI_PATTERN.search(normalize_amap_value(poi.get('type'))):
        return None
    map_address = build_poi_address(
        poi,
        city_context,
        target_administrative_unit,
    )
    if not map_address:
        return None
    return {
        'map_address': map_address,
        'map_poi_type': normalize_amap_value(poi.get('type')),
        'map_poi_typecode': normalize_amap_value(poi.get('typecode')),
    }


def select_poi_candidate(
    place_name,
    city_context,
    map_pois,
    target_administrative_unit='',
):
    """仅在地点名称唯一对应一个规范地址时返回 POI 候选。"""
    candidates = {}
    for poi in map_pois:
        candidate = build_poi_candidate(
            place_name,
            city_context,
            poi,
            target_administrative_unit,
        )
        if candidate:
            candidates.setdefault(compact_address(candidate['map_address']), candidate)
    if not candidates:
        return None, 'not_found', '未找到名称、城市和地址均匹配的 POI'
    if len(candidates) > 1:
        return None, 'ambiguous', '名称完全一致的 POI 对应多个不同地址'
    return next(iter(candidates.values())), 'poi_match', '唯一名称匹配的 POI'


def resolve_poi_address(
    address_record,
    city_context,
    api_key,
    rate_limiter,
    fetch_pois=fetch_amap_pois,
):
    """按学校或校区名称查询唯一匹配的 POI 地址。"""
    processed_record = build_map_result_record(address_record)
    if not api_key:
        processed_record.update(map_match_status='error', map_reason='未配置 AMAP_KEY')
        return processed_record, 0
    target_administrative_unit = (
        address_record.get('attributes') or {}
    ).get('administrative_unit')
    place_names = [address_record['place_name']]
    campus_name = str(
        (address_record.get('attributes') or {}).get('campus_name') or ''
    ).strip()
    if campus_name and campus_name not in place_names:
        place_names.append(campus_name)
    request_count = 0
    candidate = None
    map_match_status = ''
    map_reason = ''
    for place_name in place_names:
        map_pois, error_reason = fetch_pois(
            place_name, city_context['city_name'], api_key, rate_limiter
        )
        request_count += 1
        if error_reason:
            processed_record.update(map_match_status='error', map_reason=error_reason)
            return processed_record, request_count
        candidate, map_match_status, map_reason = select_poi_candidate(
            place_name, city_context, map_pois, target_administrative_unit
        )
        if candidate:
            break
    processed_record.update(map_match_status=map_match_status, map_reason=map_reason)
    if not candidate:
        return processed_record, request_count
    processed_record.update(candidate)
    return processed_record, request_count


def resolve_map_address(
    address_record,
    city_context,
    api_key,
    rate_limiter,
    fetch_geocodes=fetch_amap_geocodes,
    fetch_pois=fetch_amap_pois,
):
    """根据来源性质和地址完整度选择地理编码或 POI 查询。"""
    source_nature = address_record['source_nature']
    normalization_status = address_record['normalization_status']
    official_address = str(address_record.get('normalized_address') or '').strip()
    detailed_address = has_detailed_address(
        address_record,
        city_context['city_name'],
    )

    if source_nature == 'government_information' and official_address:
        if detailed_address:
            processed_record, request_count = verify_map_address(
                address_record,
                city_context,
                api_key,
                rate_limiter,
                fetch_geocodes,
            )
            processed_record.update(
                final_address=official_address,
                final_address_source='official',
                final_address_reason='政府资料地址，地图仅用于匹配验证',
            )
            return processed_record, request_count
        if has_government_specific_location(
            address_record, city_context['city_name']
        ):
            processed_record = build_map_result_record(address_record)
            processed_record.update(
                map_match_status='skipped',
                map_reason='政府资料地址缺少可验证道路或门牌组件',
                final_address=official_address,
                final_address_source='official',
                final_address_reason='政府资料地址',
            )
            return processed_record, 0
        processed_record, request_count = resolve_poi_address(
            address_record,
            city_context,
            api_key,
            rate_limiter,
            fetch_pois,
        )
        if processed_record['map_match_status'] == 'poi_match':
            processed_record.update(
                final_address=processed_record['map_address'],
                final_address_source='map',
                final_address_reason='政府资料地址不完整，按学校名称补充地图地址',
            )
            return processed_record, request_count
        processed_record.update(
            final_address=official_address,
            final_address_source='official',
            final_address_reason='政府资料地址',
        )
        return processed_record, request_count

    if (
        source_nature == 'web_search'
        and normalization_status in {'complete', 'partial'}
        and detailed_address
    ):
        processed_record, request_count = verify_map_address(
            address_record,
            city_context,
            api_key,
            rate_limiter,
            fetch_geocodes,
        )
        final_address, final_source, final_reason = choose_final_address(
            address_record,
            processed_record,
            city_context['city_name'],
        )
        if (
            normalization_status == 'partial'
            and address_record.get('normalization_reason') == MISSING_ADMIN_REASON
            and processed_record.get('map_match_status') in {'consistent', 'partial'}
            and processed_record.get('map_address')
        ):
            processed_record['map_match_status'] = 'partial'
            processed_record['map_reason'] = '地图补充下级行政区'
            final_address = processed_record['map_address']
            final_source = 'map'
            final_reason = '地图补充来源地址缺少的下级行政区'
        processed_record.update(
            final_address=final_address,
            final_address_source=final_source,
            final_address_reason=final_reason,
        )
        return processed_record, request_count

    if normalization_status in {'empty', 'partial', 'complete'} and not detailed_address:
        processed_record, request_count = resolve_poi_address(
            address_record,
            city_context,
            api_key,
            rate_limiter,
            fetch_pois,
        )
        if processed_record['map_match_status'] == 'poi_match':
            processed_record.update(
                final_address=processed_record['map_address'],
                final_address_source='map',
                final_address_reason='POI 名称匹配地址',
            )
        elif (
            normalization_status == 'complete'
            and official_address
            and processed_record['map_match_status'] in {'not_found', 'ambiguous'}
        ):
            processed_record.update(
                final_address=official_address,
                final_address_source='official',
                final_address_reason=(
                    '官网地址缺少可验证道路或门牌，地图未确认，保留来源地址'
                ),
            )
        return processed_record, request_count

    processed_record = build_map_result_record(address_record)
    normalization_reason = str(
        address_record.get('normalization_reason') or ''
    ).strip()
    processed_record.update(
        map_match_status='skipped',
        map_reason=(
            normalization_reason
            if normalization_reason
            else f'{source_nature} 的 {normalization_status} 地址不调用高德'
        ),
    )
    return processed_record, 0
