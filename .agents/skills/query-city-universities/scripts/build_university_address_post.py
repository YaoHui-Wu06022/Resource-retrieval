#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""处理高校地图结果中的同址重复记录。"""

import re


def _map_detail_key(address):
    """提取地图地址中最后道路和门牌号，用于同址判断。"""
    value = re.sub(r'\s+', '', str(address or ''))
    number_matches = list(re.finditer(r'\d+(?:[-－]\d+)?号', value))
    if not number_matches:
        return value
    number_match = number_matches[-1]
    road_positions = [
        value.rfind(suffix, 0, number_match.start())
        for suffix in ('大道', '大街', '路', '街', '巷', '弄', '道')
    ]
    road_position = max(road_positions)
    if road_position < 0:
        return value
    detail_start = 0
    for separator in ('省', '市', '区', '县', '街道', '街', '镇', '乡'):
        separator_position = value.rfind(separator, 0, road_position)
        if separator_position >= detail_start:
            detail_start = separator_position + len(separator)
    return value[detail_start:number_match.end()]


def postprocess_university_address_records(records):
    """地图同址时删除同校重复记录并优先保留校区名。"""
    retained = []
    seen = {}
    for record in records:
        attributes = record.get('attributes') or {}
        school_identifier = str(attributes.get('school_identifier') or '').strip()
        campus_name = str(attributes.get('campus_name') or '').strip()
        map_address = str(record.get('map_address') or '').strip()
        detail_key = _map_detail_key(map_address)
        key = (school_identifier, detail_key) if detail_key else None
        if not key or not map_address:
            retained.append(record)
            continue
        existing_index = seen.get(key)
        if existing_index is None:
            seen[key] = len(retained)
            retained.append(record)
            continue
        existing = retained[existing_index]
        existing_campus = str(
            (existing.get('attributes') or {}).get('campus_name') or ''
        ).strip()
        if campus_name and not existing_campus:
            retained[existing_index] = record
    return retained
