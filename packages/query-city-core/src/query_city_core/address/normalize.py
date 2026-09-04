#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规范化统一地址记录中的原始地址。"""

import re
from collections import Counter

from .city import read_city_catalog, validate_city_context
from .common import (
    ADMIN_UNIT_SUFFIXES,
    CITY_SUFFIXES,
    DISTRICT_LEVEL_SUFFIXES,
    DISTRICT_PATTERN,
    MISSING_ADMIN_REASON,
    PLACE_NAME_SUFFIXES,
    SUB_LEVEL_SUFFIXES,
    extract_admin_unit_components,
    resolve_address_mode,
    resolve_target_administrative_unit,
    validate_address_record,
)


_CITY_CATALOG = read_city_catalog()


def _city_short_names(full_name):
    """返回城市全名的常见简称；无简称时返回全名。"""
    core = full_name
    for suffix in CITY_SUFFIXES:
        if full_name.endswith(suffix):
            core = full_name[:-len(suffix)]
            break
    names = {core}
    minority_marker = core.find('族')
    if minority_marker > 0:
        names.add(core[:minority_marker])
    return names


_CITY_FULL_NAMES = frozenset(_CITY_CATALOG)
_CITY_SHORT_NAMES = set()
_CITY_SHORT_TO_FULL = {}
for _city_full_name in _CITY_CATALOG:
    for _city_short_name in _city_short_names(_city_full_name):
        _CITY_SHORT_NAMES.add(_city_short_name)
        _CITY_SHORT_TO_FULL.setdefault(_city_short_name, []).append(
            _city_full_name
        )


def _subdivision_suffixes(city_context):
    """从目标城市下级行政区名称推断其使用的层级后缀。"""
    suffixes = set()
    for item in city_context.get('subdivisions') or []:
        name = str(item.get('name') or '').strip()
        for suffix in ADMIN_UNIT_SUFFIXES:
            if name.endswith(suffix):
                suffixes.add(suffix)
                break
    return suffixes


def detect_city_prefix(address):
    """返回地址开头明确出现的城市全名或简称；未出现时返回空字符串。"""
    value = str(address or '')
    province_match = PROVINCE_PREFIX_PATTERN.match(value)
    if province_match:
        value = value[province_match.end():]
    city_match = CITY_PREFIX_PATTERN.match(value)
    if city_match:
        return city_match.group('city')
    short_city_match = CITY_SHORT_WITH_DISTRICT_PATTERN.match(value)
    if short_city_match:
        short_name = short_city_match.group('city')
        full_names = _CITY_SHORT_TO_FULL.get(short_name, ())
        if len(full_names) == 1:
            return full_names[0]
        return short_name
    return ''


def detect_foreign_city_campus(place_name, city_context):
    """地点名称中出现目标城市以外的城市校区名时返回异地城市全名。"""
    target_city = str(city_context.get('city_name') or '')
    target_short = (
        min(_city_short_names(target_city), key=len) if target_city else ''
    )
    value = str(place_name or '')
    for short_name, full_names in _CITY_SHORT_TO_FULL.items():
        if not short_name or short_name == target_short:
            continue
        if any(full_name == target_city for full_name in full_names):
            continue
        if short_name + '校区' in value or short_name + '校园' in value:
            return full_names[0] if full_names else short_name
    return ''


ADDRESS_LABEL_PATTERN = re.compile(
    r'(?:通讯地址|联系地址|邮寄地址|办公地址|学校地址|校址|地址)\s*[：:]\s*'
)
NARRATIVE_PREFIX_PATTERN = re.compile(
    r'^(?:地处|位于|坐落于|位置)\s*[：:，,]?\s*'
)
LABEL_COLON_PREFIX_PATTERN = re.compile(r'^[^：:]{1,40}[：:]\s*')
ADMIN_ADDRESS_START_PATTERN = re.compile(
    r'^(?:中国|中华人民共和国)?'
    r'(?:[\u4e00-\u9fff]{1,15}?(?:省|市|自治区|自治州|地区|盟|特别行政区)'
    r'|[\u4e00-\u9fff]{1,15}?[区县旗])'
)
BULLET_MARK_PATTERN = re.compile(r'[•●◆■□·]')
DUPLICATE_CITY_PREFIX_PATTERN = re.compile(
    r'[\u4e00-\u9fff]{1,12}市'
)
NARRATIVE_TAIL_PATTERN = re.compile(
    r'公交|地铁|学校门口|学费|收费标准|元/|学年|电话|邮编|'
    r'TEL|联系人|报名|宿舍|食堂|后勤'
)
CONTACT_TAIL_PATTERN = re.compile(
    r'\s*(?:[，,；;、|｜]\s*)?'
    r'(?:邮政编码|邮编|联系电话|电话|传真|电子邮箱|邮箱|E-?mail)\s*[：:]?.*$',
    re.IGNORECASE,
)
POSTCODE_PATTERN = re.compile(r'\s*[（(]\s*\d{6}\s*[）)]\s*$')
PROVINCE_PREFIX_PATTERN = re.compile(
    r'^(?P<province>(?:[^\s省市县区旗盟]){2,30}?'
    r'(?:特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|省))'
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
    r'街道?|' + '|'.join(
        suffix for suffix in SUB_LEVEL_SUFFIXES if suffix != '街道'
    )
    + r'|大道|公路|路|街|巷|村|社区|小区|商住|工业|园|校'
)
LOWER_ADMIN_PATTERN = re.compile(
    r'^(.{1,20}?(?:' + '|'.join(SUB_LEVEL_SUFFIXES) + r'))'
)
PLACE_ONLY_PATTERN = re.compile(
    r'^.{0,30}(?:' + '|'.join(PLACE_NAME_SUFFIXES) + r')$'
)
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
    value = BULLET_MARK_PATTERN.sub('', value)
    while True:
        stripped = NARRATIVE_PREFIX_PATTERN.sub('', value)
        if stripped == value:
            break
        value = stripped
    label_prefix = LABEL_COLON_PREFIX_PATTERN.match(value)
    if label_prefix:
        remainder = value[label_prefix.end():]
        if ADMIN_ADDRESS_START_PATTERN.match(remainder):
            value = remainder
    city_matches = list(DUPLICATE_CITY_PREFIX_PATTERN.finditer(value))
    if len(city_matches) >= 2:
        last_start = city_matches[-1].start()
        prefix = value[:last_start]
        if not re.search(r'[路街大道巷号栋座]', prefix):
            value = value[last_start:]
    separators = list(re.finditer(r'[，,；;、]', value))
    for separator in separators:
        head = value[:separator.start()]
        tail = value[separator.end():]
        if re.search(r'\d+号', head) and NARRATIVE_TAIL_PATTERN.search(tail):
            value = head
            break
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
    address = complete_short_subdivision_prefix(address, city_context)

    target_short = min(_city_short_names(city), key=len)
    if address.startswith(city):
        address = address[len(city):]
    elif (
        address.startswith(target_short)
        and DISTRICT_PATTERN.match(address[len(target_short):])
        and not is_non_administrative_zone(
            DISTRICT_PATTERN.match(address[len(target_short):]).group(1)
        )
    ):
        address = address[len(target_short):]
    else:
        city_match = CITY_PREFIX_PATTERN.match(address)
        if (
            city_match
            and city_match.group('city') in _CITY_FULL_NAMES
            and city_match.group('city') != city
        ):
            return '', (
                '原始地址中的城市与目标城市不一致：'
                f'{city_match.group("city")}'
            )
        short_city_match = CITY_SHORT_WITH_DISTRICT_PATTERN.match(address)
        if (
            short_city_match
            and not short_city_match.group('district').startswith(
                ('区', '县', '旗')
            )
            and short_city_match.group('city') in _CITY_SHORT_NAMES
            and short_city_match.group('city') != target_short
        ):
            return '', (
                '原始地址中的城市与目标城市不一致：'
                f'{short_city_match.group("city")}'
            )
    return address, ''


def complete_short_subdivision_prefix(address, city_context):
    """把“城市简称 + 无后缀子区名”的空格分词写法补全为完整子区名。"""
    city = str(city_context.get('city_name') or '').strip()
    if not city:
        return address
    target_short = min(_city_short_names(city), key=len)
    if not address.startswith(target_short):
        return address
    remainder = address[len(target_short):]
    core_to_full = {}
    for item in city_context.get('subdivisions') or []:
        name = str(item.get('name') or '').strip()
        core = name
        for suffix in (
            '特别行政区', '自治区', '自治州', '地区', '盟', '区', '县', '旗'
        ):
            if name.endswith(suffix):
                core = name[: -len(suffix)]
                break
        if core and core != name:
            core_to_full.setdefault(core, name)
    for core, full_name in sorted(
        core_to_full.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if remainder.startswith(core) and not remainder[len(core):].startswith(
            ('区', '县', '旗')
        ):
            return f'{full_name}{remainder[len(core):]}'
    return address


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
            'resolved_city': '',
        }

    cleaned_address = normalize_address_text(original_address)
    if not cleaned_address:
        return {
            'normalized_address': '',
            'normalization_status': 'invalid',
            'normalization_reason': '清理后没有可用地址',
            'resolved_city': '',
        }

    detail, conflict_reason = extract_target_city_detail(
        cleaned_address, city_context
    )
    if conflict_reason:
        foreign_city = detect_city_prefix(cleaned_address)
        return {
            'normalized_address': '',
            'normalization_status': 'conflict',
            'normalization_reason': conflict_reason,
            'resolved_city': foreign_city,
        }

    target_administrative_unit = re.sub(
        r'\s+', '', str(target_administrative_unit or '')
    )
    target_unit_index = detail.find(target_administrative_unit)
    if target_administrative_unit and 0 <= target_unit_index <= 20:
        detail = detail[target_unit_index:]
    subdivision_names = {
        str(item.get('name') or '').strip()
        for item in city_context.get('subdivisions') or []
    }
    admin_unit, _ = extract_admin_unit_components(detail)
    if admin_unit:
        admin_suffix = next(
            suffix for suffix in ADMIN_UNIT_SUFFIXES
            if admin_unit.endswith(suffix)
        )
        city_suffixes = _subdivision_suffixes(city_context)
        location_after_admin = detail[len(admin_unit):]
        if admin_suffix == '市' and re.match(
            r'^(?:[东南西北中])?(?:路|街|大道|巷)',
            location_after_admin,
        ):
            admin_unit = ''
        elif (
            admin_suffix not in SUB_LEVEL_SUFFIXES
            and is_non_administrative_zone(admin_unit)
        ):
            admin_unit = ''
        elif subdivision_names:
            known_local = any(
                name == admin_unit or name.startswith(admin_unit)
                for name in subdivision_names
            )
            if not known_local:
                if (
                    admin_suffix in city_suffixes
                    or admin_suffix in DISTRICT_LEVEL_SUFFIXES
                ):
                    return {
                        'normalized_address': '',
                        'normalization_status': 'conflict',
                        'normalization_reason': (
                            '原始地址中的下级行政区不属于目标城市：'
                            f'{admin_unit}'
                        ),
                        'resolved_city': city,
                    }
                admin_unit = ''
        elif admin_suffix in SUB_LEVEL_SUFFIXES:
            admin_unit = ''
    location = detail[len(admin_unit):] if admin_unit else detail
    if (
        admin_unit
        and target_administrative_unit
        and admin_unit != target_administrative_unit
    ):
        return {
            'normalized_address': '',
            'normalization_status': 'conflict',
            'normalization_reason': (
                '原始地址中的下级行政区与检索单元不一致：'
                f'{admin_unit} != {target_administrative_unit}'
            ),
            'resolved_city': city,
        }
    if not admin_unit and target_administrative_unit:
        detail = f'{target_administrative_unit}{detail}'
        admin_unit = target_administrative_unit
    normalized_address = f'{city}{detail}'
    reason = ''
    if not admin_unit:
        reason = MISSING_ADMIN_REASON
    elif not has_specific_location(location):
        reason = '地址缺少行政区之后的具体位置'
    return {
        'normalized_address': normalized_address,
        'normalization_status': 'partial' if reason else 'complete',
        'normalization_reason': reason,
        'resolved_city': city,
    }


def normalize_address_record(address_record, city_context):
    """保留业务字段并规范化一条公共地址记录。"""
    validate_address_record(address_record)
    attributes = dict(address_record.get('attributes') or {})
    place_name = str(address_record.get('place_name') or '').strip()
    address_mode = resolve_address_mode(address_record)
    normalized_fields = normalize_address_value(
        address_record.get('original_address'),
        city_context,
        resolve_target_administrative_unit(address_record),
    )
    foreign_city = detect_foreign_city_campus(place_name, city_context)
    if foreign_city and not normalized_fields.get('normalized_address'):
        return {
            **address_record,
            'address_mode': address_mode,
            'place_name': place_name,
            'original_address': str(
                address_record.get('original_address') or ''
            ).strip(),
            'source_reference': str(address_record['source_reference']).strip(),
            'attributes': attributes,
            'normalized_address': '',
            'normalization_status': 'conflict',
            'normalization_reason': f'地点名称包含异地城市校区：{foreign_city}',
            'resolved_city': foreign_city,
        }
    return {
        **address_record,
        'address_mode': address_mode,
        'place_name': place_name,
        'original_address': str(address_record.get('original_address') or '').strip(),
        'source_reference': str(address_record['source_reference']).strip(),
        'attributes': attributes,
        **normalized_fields,
    }


def is_structurally_valid_address(address_record, city_context):
    """判断规范地址是否已是可直接采用的目标城市有效地址。"""
    return (
        address_record.get('normalization_status') == 'complete'
        and bool(str(address_record.get('normalized_address') or '').strip())
        and address_record.get('resolved_city')
        == city_context['city_name']
    )


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
