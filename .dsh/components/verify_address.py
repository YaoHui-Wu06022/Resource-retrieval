#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用地图地理编码交叉验证完整规范地址。"""

import re

from amap_client import fetch_amap_geocodes, normalize_amap_value
from normalize_address import extract_address_components


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
    r'([\u4e00-\u9fffA-Za-z0-9·\-]{1,20}(?:校区|校园|分院|分行|支行|分部))'
)
ADMIN_SUFFIX_PATTERN = re.compile(
    r'(?:特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|自治州|地区|盟|省|市|区|县|旗)$'
)
MUNICIPALITIES = {'北京市', '天津市', '上海市', '重庆市'}
STATUS_PRIORITY = {'consistent': 0, 'partial': 1, 'conflict': 2}


def compact_address(value):
    """移除地址比较中无意义的空白和常见标点。"""
    return re.sub(r'[\s，,。；;：:（）()]+', '', str(value or ''))


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
    return 'partial' if source_base == map_base else 'conflict'


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
    detail = (
        normalized_address[len(city):]
        if normalized_address.startswith(city)
        else normalized_address
    )
    district, location = extract_address_components(detail)
    return {
        'province': '',
        'city': city,
        'district': district,
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
    district = normalize_amap_value(map_candidate.get('district'))
    if not city and source_components.get('city') in MUNICIPALITIES:
        city = province
    detail = extract_map_address_detail(address, (province, city, district))
    return {
        'province': province,
        'city': city,
        'district': district,
        'street': normalize_amap_value(
            map_candidate.get('street')
        ) or extract_road_name(detail),
        'number': normalize_amap_value(
            map_candidate.get('number')
        ) or extract_house_number(detail),
        'address': address,
    }


def compare_admin_components(source, map_components):
    """比较双方明确提供的城市和区县并返回缺失信息。"""
    missing = []
    labels = {'city': '城市', 'district': '区县'}
    for field in ('city', 'district'):
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
        map_status, map_reason = judge_address_match(
            source_address, source_components, map_components
        )
        judged_candidates.append({
            'map_address': map_components['address'],
            'map_status': map_status,
            'map_reason': map_reason,
            'map_poi_type': '',
            'map_poi_typecode': '',
        })
    if not judged_candidates:
        return None
    return min(
        judged_candidates,
        key=lambda map_candidate: STATUS_PRIORITY[map_candidate['map_status']],
    )


def verify_map_address(
    address_record,
    city,
    api_key,
    rate_limiter,
    fetch_geocodes=fetch_amap_geocodes,
):
    """查询地图并返回不改变规范地址的验证结果。"""
    processed_record = {
        **address_record,
        'map_address': '',
        'map_status': '',
        'map_reason': '',
        'map_poi_type': '',
        'map_poi_typecode': '',
    }
    if not api_key:
        processed_record.update(map_status='error', map_reason='未配置 AMAP_KEY')
        return processed_record, 0
    map_candidates, error_reason = fetch_geocodes(
        address_record['normalized_address'], city, api_key, rate_limiter
    )
    if error_reason:
        processed_record.update(map_status='error', map_reason=error_reason)
        return processed_record, 1
    selected_candidate = choose_map_result(
        address_record, city, map_candidates
    )
    if not selected_candidate:
        processed_record.update(
            map_status='not_found',
            map_reason='高德服务正常但未找到结果',
        )
        return processed_record, 1
    processed_record.update(selected_candidate)
    return processed_record, 1
