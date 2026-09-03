"""医疗机构 Skill 共用的地址拆分、去重与记录构造。"""

import re

from query_city_core.address.common import (
    SUBDIVISION_SCOPE_SUBDIVISION,
    address_equivalence_key,
)
from query_city_core.address.city import read_city_catalog


ADDRESS_SPLIT_PATTERN = re.compile(r'[、，,；;\r\n]+')
ADDRESS_MARKER_PATTERN = re.compile(
    r'大道|大路|公路|路|街|巷|道|号|村|城|大厦|花园|花苑|苑|'
    r'广场|中心|工业区|产业园|社区|小区|院|大楼'
)
_CITY_CATALOG = None


def normalize_compact_text(value):
    """删除文本中的全部空白。"""
    return re.sub(r'\s+', '', str(value or ''))


def split_address_segments(value):
    """把官方地址整格拆成可独立定位的地址段。

    “2层”“西北区”等只有楼层/方位的片段会拼回上一段，保留官方原文。
    """
    parts = ADDRESS_SPLIT_PATTERN.split(str(value or ''))
    segments = []
    for part in parts:
        part = part.strip().strip('、，,；;')
        if not part:
            continue
        if segments and not ADDRESS_MARKER_PATTERN.search(part):
            segments[-1] = segments[-1] + '、' + part
            continue
        segments.append(part)
    return segments


def derive_administrative_unit(segment, default_unit, city_context):
    """从地址段提取区县；没有时使用来源行行政区划。"""
    for subdivision in city_context.get('subdivisions') or []:
        name = (
            subdivision.get('name')
            if isinstance(subdivision, dict)
            else str(subdivision or '')
        ).strip()
        if name and name in str(segment or ''):
            return name
    return str(default_unit or '').strip()


def is_foreign_address_segment(
    segment,
    city_context,
    foreign_phrases=(),
):
    """判断地址段是否明确指向目标城市以外。"""
    segment_text = normalize_compact_text(segment)
    target_city = str(city_context.get('city_name') or '')
    if not segment_text:
        return False
    global _CITY_CATALOG
    if _CITY_CATALOG is None:
        try:
            _CITY_CATALOG = read_city_catalog()
        except (OSError, ValueError):
            _CITY_CATALOG = {}
    catalog = _CITY_CATALOG
    for city_name in catalog:
        if not city_name or city_name == target_city:
            continue
        if city_name in segment_text:
            return True
    return any(
        phrase and phrase in segment_text
        for phrase in foreign_phrases
    )


def build_medical_record(
    source_id,
    place_name,
    address_segment,
    source_row,
    source_reference,
    city_context,
    administrative_unit,
    institution_type='',
    institution_level='',
    license_no='',
    source_authority='',
    snapshot_date='',
    merge_priority=10,
    license_administrative_unit=None,
):
    """构造单条公共地址记录。"""
    if license_administrative_unit is None:
        license_administrative_unit = administrative_unit
    return {
        'place_name': normalize_compact_text(place_name),
        'original_address': address_segment.strip(),
        'address_mode': 'government_list',
        'source_nature': 'government_information',
        'source_reference': source_reference,
        'attributes': {
            'administrative_unit': derive_administrative_unit(
                address_segment,
                administrative_unit,
                city_context,
            ),
            'subdivision_scope': SUBDIVISION_SCOPE_SUBDIVISION,
            'license_administrative_unit': str(
                license_administrative_unit or ''
            ).strip(),
            'institution_type': str(institution_type or '').strip(),
            'institution_level': str(institution_level or '').strip(),
            'license_no': str(license_no or '').strip(),
            'source_id': source_id,
            'source_authority': str(source_authority or '').strip(),
            'snapshot_date': str(snapshot_date or '').strip(),
            'source_row': source_row,
        },
        '_merge_priority': int(merge_priority),
    }


def record_quality_score(record, priority):
    """跨来源合并时选择信息更完整的记录。"""
    attributes = record.get('attributes') or {}
    has_type = bool(str(attributes.get('institution_type') or '').strip())
    has_level = bool(str(attributes.get('institution_level') or '').strip())
    has_license = bool(str(attributes.get('license_no') or '').strip())
    return (
        int(has_type and has_level),
        int(has_type),
        int(has_level),
        int(has_license),
        -priority,
    )


def deduplicate_records(records):
    """按登记号或机构名+地址合并跨来源记录。"""
    retained = []
    indexes = {}
    for order, record in enumerate(records):
        attributes = record.get('attributes') or {}
        license_no = str(attributes.get('license_no') or '').strip()
        if license_no:
            key = (
                'license',
                license_no,
                address_equivalence_key(record.get('original_address')),
            )
        else:
            key = (
                'address',
                normalize_compact_text(record.get('place_name')),
                str(attributes.get('administrative_unit') or '').strip(),
                address_equivalence_key(record.get('original_address')),
            )
        existing_index = indexes.get(key)
        priority = int(record.get('_merge_priority') or 10)
        if existing_index is None:
            indexes[key] = len(retained)
            retained.append(record)
            continue
        existing = retained[existing_index]
        existing_priority = int(existing.get('_merge_priority') or 10)
        if record_quality_score(
            record, priority
        ) > record_quality_score(existing, existing_priority):
            retained[existing_index] = record
    return retained
