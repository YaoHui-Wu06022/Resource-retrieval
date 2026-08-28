#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规范化统一地址记录中的原始地址。"""

import json
import re
from collections import Counter
from pathlib import Path

from ..city import validate_city_context
from .common import (
    DISTRICT_PATTERN,
    extract_address_components,
    validate_address_record,
)


ADDRESS_LABEL_PATTERN = re.compile(
    r'(?:通讯地址|联系地址|邮寄地址|办公地址|学校地址|校址|地址)\s*[：:]\s*'
)
CONTACT_TAIL_PATTERN = re.compile(
    r'\s*(?:[，,；;、|｜]\s*)?'
    r'(?:邮政编码|邮编|联系电话|电话|传真|电子邮箱|邮箱|E-?mail)\s*[：:]?.*$',
    re.IGNORECASE,
)
POSTCODE_PATTERN = re.compile(r'\s*[（(]\s*\d{6}\s*[）)]\s*$')
PROVINCE_PREFIX_PATTERN = re.compile(
    r'^(?P<province>[\u4e00-\u9fff]{2,30}?(?:特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|省))'
)
CITY_PREFIX_PATTERN = re.compile(
    r'^(?P<city>[\u4e00-\u9fff]{2,30}?(?:自治州|地区|盟|市))'
)
CITY_SHORT_WITH_DISTRICT_PATTERN = re.compile(
    r'^(?P<city>[\u4e00-\u9fff]{2,20}?)(?P<district>[\u4e00-\u9fff]{1,15}?(?:区|县|旗))'
)
FUNCTIONAL_ZONE_PATTERN = re.compile(
    r'^(?:.*?)(?:经济技术开发区|高新技术产业开发区|开发区|高新区|产业园区)$'
)
NON_ADMIN_ZONE_MARKER_PATTERN = re.compile(
    r'街道?|镇|乡|苏木|大道|公路|路|街|巷|村|社区|小区|商住|工业|园|校'
)
LOWER_ADMIN_PATTERN = re.compile(r'^(.{1,20}?(?:街道|镇|乡|苏木))')
PLACE_ONLY_PATTERN = re.compile(r'^.{0,30}(?:校区|校园|分院|分行|支行|分部)$')
SPECIFIC_ADDRESS_PATTERN = re.compile(
    r'(?:大道|道路|公路|路|街|巷|弄|段|村|大院|\d+号|\d+栋|\d+座|\d+楼)'
)
PUNCTUATION_MAP = str.maketrans({
    '(': '（',
    ')': '）',
    ',': '，',
    ';': '；',
    ':': '：',
})


def normalize_address_text(original_address):
    """清理地址标签、联系方式、邮编和空白。"""
    value = str(original_address or '').replace('\u3000', ' ')
    value = ADDRESS_LABEL_PATTERN.sub('', value)
    value = CONTACT_TAIL_PATTERN.sub('', value)
    value = POSTCODE_PATTERN.sub('', value)
    value = re.sub(r'\s+', '', value)
    value = value.translate(PUNCTUATION_MAP)
    value = value.strip('，,；;：:|｜ ')
    while value.endswith('）') and value.count('）') > value.count('（'):
        value = value[:-1]
    while value.startswith('（') and value.count('（') > value.count('）'):
        value = value[1:]
    return value


def extract_target_city_detail(address, city_context):
    """移除目标行政前缀并拒绝明确的异地地址。"""
    address = re.sub(r'^(?:中华人民共和国|中国)', '', address)
    city = city_context['city_name']
    province = city_context['province_name']
    target_province_matched = False
    if province and address.startswith(province):
        address = address[len(province):]
        target_province_matched = True
    elif province and province.endswith('省') and address.startswith(province[:-1]):
        address = address[len(province) - 1:]
        target_province_matched = True
    else:
        province_match = PROVINCE_PREFIX_PATTERN.match(address)
        if province_match:
            return '', (
                '原始地址中的省级单位与目标城市不一致：'
                f'{province_match.group("province")}'
            )

    if address.startswith(city):
        address = address[len(city):]
    elif (
        city.endswith('市')
        and address.startswith(city[:-1])
        and DISTRICT_PATTERN.match(address[len(city) - 1:])
        and not is_non_administrative_zone(
            DISTRICT_PATTERN.match(address[len(city) - 1:]).group(1)
        )
    ):
        address = address[len(city) - 1:]
    else:
        city_match = CITY_PREFIX_PATTERN.match(address)
        if city_match:
            foreign_city = city_match.group('city')
            remaining = address[city_match.end():]
            district_match = DISTRICT_PATTERN.match(remaining)
            has_administrative_district = (
                district_match is not None
                and not is_non_administrative_zone(district_match.group(1))
            )
            if target_province_matched or has_administrative_district:
                return '', (
                    '原始地址中的城市与目标城市不一致：'
                    f'{foreign_city}'
                )
        if target_province_matched:
            short_city_match = CITY_SHORT_WITH_DISTRICT_PATTERN.match(address)
            if short_city_match:
                return '', (
                    '原始地址中的城市与目标城市不一致：'
                    f'{short_city_match.group("city")}'
                )
    return address, ''


def is_non_administrative_zone(zone_name):
    """判断区县候选是否只是功能区或具体位置。"""
    return bool(
        FUNCTIONAL_ZONE_PATTERN.fullmatch(zone_name)
        or NON_ADMIN_ZONE_MARKER_PATTERN.search(zone_name[:-1])
        or (zone_name.endswith('旗') and len(zone_name) <= 2)
    )


def has_specific_location(location):
    """判断区县及基层行政区之后是否还有具体位置。"""
    remaining = str(location or '')
    while True:
        match = LOWER_ADMIN_PATTERN.match(remaining)
        if not match:
            break
        remaining = remaining[len(match.group(1)):]
    if SPECIFIC_ADDRESS_PATTERN.search(remaining):
        return True
    return len(remaining) >= 2 and not PLACE_ONLY_PATTERN.fullmatch(remaining)


def normalize_address_value(
    original_address,
    city_context,
    target_administrative_unit='',
):
    """把一个地址文本规范化为目标城市下的地址。"""
    city = city_context['city_name']
    if not str(original_address or '').strip():
        return {
            'normalized_address': '',
            'normalization_status': 'empty',
            'normalization_reason': '前置处理没有取得地址文本',
        }

    cleaned_address = normalize_address_text(original_address)
    if not cleaned_address:
        return {
            'normalized_address': '',
            'normalization_status': 'invalid',
            'normalization_reason': '清理后没有可用地址',
        }

    detail, conflict_reason = extract_target_city_detail(
        cleaned_address, city_context
    )
    if conflict_reason:
        return {
            'normalized_address': '',
            'normalization_status': 'conflict',
            'normalization_reason': conflict_reason,
        }

    target_administrative_unit = re.sub(
        r'\s+', '', str(target_administrative_unit or '')
    )
    target_unit_index = detail.find(target_administrative_unit)
    if target_administrative_unit and 0 <= target_unit_index <= 20:
        detail = detail[target_unit_index:]
    district, location = extract_address_components(detail)
    if district and is_non_administrative_zone(district):
        district = ''
        location = detail
    if (
        district
        and target_administrative_unit
        and district != target_administrative_unit
    ):
        return {
            'normalized_address': '',
            'normalization_status': 'conflict',
            'normalization_reason': (
                '原始地址中的区县与检索单元不一致：'
                f'{district} != {target_administrative_unit}'
            ),
        }
    if not district and target_administrative_unit:
        detail = f'{target_administrative_unit}{detail}'
        district = target_administrative_unit
    normalized_address = f'{city}{detail}'
    reason = ''
    if not district:
        reason = '地址缺少区县'
    elif not has_specific_location(location):
        reason = '地址缺少行政区之后的具体位置'
    return {
        'normalized_address': normalized_address,
        'normalization_status': 'partial' if reason else 'complete',
        'normalization_reason': reason,
    }


def normalize_address_record(address_record, city_context):
    """保留业务字段并规范化一条公共地址记录。"""
    validate_address_record(address_record)
    attributes = dict(address_record.get('attributes') or {})
    normalized_fields = normalize_address_value(
        address_record.get('original_address'),
        city_context,
        attributes.get('administrative_unit'),
    )
    return {
        **address_record,
        'place_name': str(address_record['place_name']).strip(),
        'original_address': str(
            address_record.get('original_address') or ''
        ).strip(),
        'source_reference': str(address_record['source_reference']).strip(),
        'attributes': attributes,
        **normalized_fields,
    }


def normalize_address_payload(input_payload):
    """按输入顺序规范化统一地址记录。"""
    if (
        not isinstance(input_payload, dict)
        or input_payload.get('stage') != 'address_records'
    ):
        raise ValueError('输入必须是 address_records JSON')
    city_context = validate_city_context(input_payload.get('city_context'))
    address_records = input_payload.get('items')
    if not isinstance(address_records, list):
        raise ValueError('items 必须是数组')
    normalized_records = [
        normalize_address_record(address_record, city_context)
        for address_record in address_records
    ]
    status_counts = Counter(
        address_record['normalization_status']
        for address_record in normalized_records
    )
    return {
        'stage': 'normalized_address_records',
        'city_context': city_context,
        'items': normalized_records,
        'metrics': {
            'item_count': len(normalized_records),
            'status_counts': dict(sorted(status_counts.items())),
        },
    }


def write_json_payload(output_path, output_payload):
    """把公共地址结果写入 UTF-8 JSON。"""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(output_payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
