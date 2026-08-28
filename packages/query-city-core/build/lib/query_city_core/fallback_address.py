#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在允许兜底时使用高德 POI 补充单条地点地址。"""

import re

from .amap_client import fetch_amap_pois, normalize_amap_value
from .normalize_address import normalize_address_value


AUXILIARY_POI_PATTERN = re.compile(
    r'公交车站|地铁站|停车场|出入口|通行设施|收费站|服务区'
)
NAME_FORMAT_PATTERN = re.compile(r'[\s()（）\[\]【】{}《》<>·\-—–_]')


def normalize_place_name(value):
    """移除地点名称中不影响身份的空白、括号和连接符。"""
    return NAME_FORMAT_PATTERN.sub('', str(value or '')).strip()


def compact_address(value):
    """移除地址去重时无意义的空白和常见标点。"""
    return re.sub(r'[\s，,。；;：:（）()]+', '', str(value or ''))


def is_target_city_poi(poi, city):
    """判断 POI 返回城市是否与目标城市一致。"""
    poi_city = normalize_place_name(
        normalize_amap_value(poi.get('cityname'))
    )
    return poi_city == normalize_place_name(city)


def is_target_administrative_unit_poi(poi, administrative_unit):
    """判断 POI 区县是否与来源检索单元一致。"""
    if not administrative_unit:
        return True
    poi_unit = normalize_place_name(normalize_amap_value(poi.get('adname')))
    return poi_unit == normalize_place_name(administrative_unit)


def is_auxiliary_poi(poi):
    """根据高德原生类型排除明显的附属交通设施。"""
    poi_type = normalize_amap_value(poi.get('type'))
    return bool(AUXILIARY_POI_PATTERN.search(poi_type))


def build_fallback_address(
    poi, city, city_prefixes, target_administrative_unit=''
):
    """把 POI 区县和详细地址规范化为可用地图地址。"""
    district = normalize_amap_value(poi.get('adname'))
    detail = normalize_amap_value(poi.get('address'))
    if not detail:
        return ''
    if detail.startswith(city):
        raw_address = detail
    elif district and detail.startswith(district):
        raw_address = f'{city}{detail}'
    else:
        raw_address = f'{city}{district}{detail}'
    normalized = normalize_address_value(
        raw_address,
        city,
        city_prefixes,
        target_administrative_unit,
    )
    if normalized['normalization_status'] != 'complete':
        return ''
    return normalized['normalized_address']


def build_fallback_candidate(
    place_name,
    city,
    map_poi,
    city_prefixes,
    target_administrative_unit='',
):
    """把名称、城市、类型和地址均合格的 POI 转为候选。"""
    poi_name = normalize_amap_value(map_poi.get('name'))
    if normalize_place_name(place_name) != normalize_place_name(poi_name):
        return None
    if (
        not is_target_city_poi(map_poi, city)
        or not is_target_administrative_unit_poi(
            map_poi, target_administrative_unit
        )
        or is_auxiliary_poi(map_poi)
    ):
        return None
    map_address = build_fallback_address(
        map_poi,
        city,
        city_prefixes,
        target_administrative_unit,
    )
    if not map_address:
        return None
    return {
        'map_address': map_address,
        'map_poi_type': normalize_amap_value(map_poi.get('type')),
        'map_poi_typecode': normalize_amap_value(map_poi.get('typecode')),
    }


def select_fallback_candidate(
    place_name,
    city,
    map_pois,
    city_prefixes,
    target_administrative_unit='',
):
    """按地址去重并仅在候选地址唯一时返回结果。"""
    map_candidates = {}
    for map_poi in map_pois:
        map_candidate = build_fallback_candidate(
            place_name,
            city,
            map_poi,
            city_prefixes,
            target_administrative_unit,
        )
        if map_candidate:
            map_candidates.setdefault(
                compact_address(map_candidate['map_address']), map_candidate
            )
    if not map_candidates:
        return None, 'not_found', '没有符合名称、行政区、类型和完整地址规则的 POI'
    if len(map_candidates) > 1:
        return None, 'ambiguous', '名称完全一致的 POI 对应多个不同地址'
    return (
        next(iter(map_candidates.values())),
        'fallback',
        '唯一合格 POI 已用于地址兜底',
    )


def resolve_fallback_map_address(
    address_record,
    city,
    api_key,
    city_prefixes,
    rate_limiter,
    fetch_pois=fetch_amap_pois,
):
    """查询单条地点并返回不扩展记录的地图兜底结果。"""
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

    map_pois, error_reason = fetch_pois(
        address_record['place_name'], city, api_key, rate_limiter
    )
    if error_reason:
        processed_record.update(map_status='error', map_reason=error_reason)
        return processed_record, 1

    map_candidate, map_status, map_reason = select_fallback_candidate(
        address_record['place_name'],
        city,
        map_pois,
        city_prefixes,
        (address_record.get('attributes') or {}).get('administrative_unit'),
    )
    processed_record.update(map_status=map_status, map_reason=map_reason)
    if map_candidate:
        processed_record.update(map_candidate)
    return processed_record, 1
