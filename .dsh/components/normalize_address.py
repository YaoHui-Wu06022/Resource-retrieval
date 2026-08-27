#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规范化统一地址记录中的原始地址。"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from normalize_city import DEFAULT_ASSET_PATH, read_city_prefix_asset


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


SOURCE_NATURES = {'web_search', 'government_information'}
ADDRESS_LABEL_PATTERN = re.compile(
    r'^\s*(?:(?:[^：:\s]{1,30})(?:校区|校园)\s*)?'
    r'(?:通讯地址|联系地址|邮寄地址|办公地址|学校地址|校址|地址)\s*[：:]\s*'
)
CONTACT_TAIL_PATTERN = re.compile(
    r'\s*(?:[，,；;、|｜]\s*)?'
    r'(?:邮政编码|邮编|联系电话|电话|传真|电子邮箱|邮箱|E-?mail)\s*[：:]?.*$',
    re.IGNORECASE,
)
POSTCODE_PATTERN = re.compile(r'\s*[（(]\s*\d{6}\s*[）)]\s*$')
DISTRICT_PATTERN = re.compile(r'^(.{1,15}?(?:区|县|旗))')
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
    return value.strip('，,；;：:|｜ ')


def select_matching_admin_prefix(address, names):
    """查找地址开头最长的行政区名称。"""
    return next(
        (name for name in sorted(names, key=len, reverse=True) if address.startswith(name)),
        '',
    )


def extract_target_city_detail(address, city, province, city_prefixes):
    """移除地址中已有的目标省市并检测城市冲突。"""
    province_names = {value for value in city_prefixes.values() if value}
    province_in_address = select_matching_admin_prefix(address, province_names)
    if province_in_address and province_in_address != province:
        return '', f'原始地址中的省级行政区与目标城市不一致：{province_in_address}'
    if province_in_address:
        address = address[len(province_in_address):]

    city_in_address = select_matching_admin_prefix(address, city_prefixes)
    if city_in_address and city_in_address != city:
        return '', f'原始地址中的城市与目标城市不一致：{city_in_address}'
    while address.startswith(city):
        address = address[len(city):]
    return address, ''


def extract_address_components(detail):
    """从城市之后的文本中提取区县和具体位置。"""
    district_match = DISTRICT_PATTERN.match(detail)
    district = district_match.group(1) if district_match else ''
    location = detail[len(district):] if district else detail
    return district, location


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


def normalize_address_value(original_address, city, city_prefixes):
    """把一个地址文本规范化为目标城市下的地址。"""
    if city not in city_prefixes:
        raise ValueError(f'城市不在固定资产中：{city}')
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

    province = city_prefixes[city]
    detail, conflict_reason = extract_target_city_detail(
        cleaned_address, city, province, city_prefixes
    )
    if conflict_reason:
        return {
            'normalized_address': '',
            'normalization_status': 'conflict',
            'normalization_reason': conflict_reason,
        }

    district, location = extract_address_components(detail)
    normalized_address = f'{city}{detail}'
    reason = ''
    if not has_specific_location(location):
        reason = '地址缺少行政区之后的具体位置'
    elif not province and not district:
        reason = '直辖市地址缺少区县'
    return {
        'normalized_address': normalized_address,
        'normalization_status': 'partial' if reason else 'complete',
        'normalization_reason': reason,
    }


def validate_address_record(address_record):
    """校验公共地址记录的固定输入字段。"""
    if not isinstance(address_record, dict):
        raise ValueError('每条地址记录必须是对象')
    if not str(address_record.get('place_name') or '').strip():
        raise ValueError('每条地址记录必须包含非空 place_name')
    if 'original_address' not in address_record:
        raise ValueError('每条地址记录必须包含 original_address 字段')
    if address_record.get('source_nature') not in SOURCE_NATURES:
        raise ValueError('source_nature 必须是 web_search 或 government_information')
    if not str(address_record.get('source_reference') or '').strip():
        raise ValueError('每条地址记录必须包含非空 source_reference')
    if not isinstance(address_record.get('attributes') or {}, dict):
        raise ValueError('attributes 必须是对象')


def normalize_address_record(address_record, city, city_prefixes):
    """保留业务字段并规范化一条公共地址记录。"""
    validate_address_record(address_record)
    normalized_fields = normalize_address_value(
        address_record.get('original_address'), city, city_prefixes
    )
    return {
        **address_record,
        'place_name': str(address_record['place_name']).strip(),
        'original_address': str(
            address_record.get('original_address') or ''
        ).strip(),
        'source_reference': str(address_record['source_reference']).strip(),
        'attributes': dict(address_record.get('attributes') or {}),
        **normalized_fields,
    }


def normalize_address_payload(input_payload, city_prefixes):
    """按输入顺序规范化统一地址记录。"""
    if (
        not isinstance(input_payload, dict)
        or input_payload.get('stage') != 'address_records'
    ):
        raise ValueError('输入必须是 address_records JSON')
    city = str(input_payload.get('city') or '').strip()
    if city not in city_prefixes:
        raise ValueError(f'城市不在固定资产中：{city}')
    address_records = input_payload.get('items')
    if not isinstance(address_records, list):
        raise ValueError('items 必须是数组')
    normalized_records = [
        normalize_address_record(address_record, city, city_prefixes)
        for address_record in address_records
    ]
    status_counts = Counter(
        address_record['normalization_status']
        for address_record in normalized_records
    )
    return {
        'schema_version': '1.0',
        'stage': 'normalized_address_records',
        'city': city,
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


def main():
    """读取统一地址记录并输出规范化结果。"""
    parser = argparse.ArgumentParser(description='规范化统一地址记录')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        with Path(args.input).resolve().open(encoding='utf-8') as stream:
            input_payload = json.load(stream)
        normalized_payload = normalize_address_payload(
            input_payload, read_city_prefix_asset()
        )
        write_json_payload(args.output, normalized_payload)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'output': str(Path(args.output).resolve()),
        **normalized_payload['metrics'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
