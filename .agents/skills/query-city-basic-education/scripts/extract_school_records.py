"""执行已复核规则并构造基础教育学校地址记录。"""

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from query_city_core.official.readers import (
    load_source_html,
    load_source_tables,
    normalize_text,
)
from query_city_core.address.city import validate_city_context
from query_city_core.io_utils import read_json_payload
from query_city_core.official.extract import (
    build_source_reference,
    extract_government_records,
    extract_text_segments,
    is_table_location_match,
    normalize_key_value_label,
    read_key_value_field,
    read_table_cell,
    resolve_source_path,
    validate_positive_index,
)
from inspect_government_source import (
    ADDRESS_HEADERS,
    EXACT_PLACE_HEADERS,
    PLACE_HEADERS,
    SCHOOL_NATURE_HEADERS,
    SCHOOL_TYPE_HEADERS,
    SCHOOL_FIELD_TERMS,
    is_place_name_header,
)
from normalize_school_records import (
    build_poi_name_aliases,
    deduplicate_school_records,
    infer_school_type_from_stage_name,
    normalize_place_name_text,
    normalize_school_nature,
    normalize_school_type,
    resolve_publication_date,
    split_explicit_campus_addresses,
)

NON_RECORD_NAME_PATTERN = re.compile(
    r'^(?:更新时间|更新日期|数据截止|截至日期|填表|制表|备注|说明|合计|总计)'
)


def classify_school_type_from_presence(
    table_row: list[str], column_mappings: list[dict[str, Any]]
) -> str:
    """根据非零招生人数列推断学校类型，不决定是否保留学校。"""
    school_types = []
    for column_mapping in column_mappings:
        cell_value = read_table_cell(table_row, column_mapping['column'])
        if cell_value not in {'', '0', '0.0', '/', '-', '—'}:
            school_types.append(column_mapping['value'])
    return '、'.join(dict.fromkeys(school_types))


def build_school_record(
    place_name: str,
    original_address: str,
    school_type: str,
    school_nature: str,
    source_record: dict[str, Any],
    source_location: str,
    administrative_unit: str,
) -> dict[str, Any]:
    """生成公共地址输入记录。"""
    normalized_place_name = normalize_place_name_text(place_name)
    normalized_school_type = (
        infer_school_type_from_stage_name(normalized_place_name)
        or normalize_school_type(school_type)
    )
    return {
        'place_name': normalized_place_name,
        'original_address': normalize_text(original_address),
        'source_nature': 'government_information',
        'address_mode': 'government_list',
        'source_reference': build_source_reference(
            source_record, source_location
        ),
        'attributes': {
            'administrative_unit': administrative_unit,
            'school_type': normalized_school_type,
            'poi_name_aliases': build_poi_name_aliases(
                normalized_place_name,
                normalized_school_type,
            ),
            'school_nature': normalize_school_nature(school_nature),
            'publication_date': resolve_publication_date(
                source_record.get('publication_date')
            ),
        },
    }


def build_records_for_locations(
    place_name: str,
    original_address: str,
    school_type: str,
    school_nature: str,
    source_record: dict[str, Any],
    source_location: str,
    administrative_unit: str,
) -> list[dict[str, Any]]:
    """拆分明确校区地址并为每个地点生成学校记录。"""
    records = []
    campus_locations = split_explicit_campus_addresses(
        place_name, original_address
    )
    for location_index, (location_name, location_address) in enumerate(
        campus_locations, start=1
    ):
        record_location = source_location
        if len(campus_locations) > 1:
            record_location += f' | address {location_index}'
        records.append(build_school_record(
            location_name,
            location_address,
            school_type,
            school_nature,
            source_record,
            record_location,
            administrative_unit,
        ))
    return records


def is_non_school_record_name(place_name: str) -> bool:
    """识别表尾说明、合计和更新时间。"""
    return bool(NON_RECORD_NAME_PATTERN.search(normalize_text(place_name)))


def extract_school_records(plan_path: Path) -> tuple[dict[str, Any], int]:
    """调用公共提取引擎并生成公共地址输入。"""
    extraction_plan = read_json_payload(plan_path)
    if extraction_plan.get('stage') != 'basic_education_extraction_plan':
        raise ValueError('输入必须是 basic_education_extraction_plan JSON')
    administrative_unit = normalize_text(
        (extraction_plan.get('administrative_unit') or {}).get('name')
    )

    def build_address_records(raw_item):
        attributes = raw_item.get('attributes') or {}
        return build_records_for_locations(
            raw_item['place_name'],
            raw_item['original_address'],
            str(attributes.get('school_type') or ''),
            str(attributes.get('school_nature') or ''),
            raw_item.get('source_item') or {},
            raw_item['source_reference'],
            administrative_unit,
        )

    records, engine_metrics, error_messages = extract_government_records(
        Path(plan_path).resolve(),
        plan_stage='basic_education_extraction_plan',
        terms=SCHOOL_FIELD_TERMS,
        build_address_records=build_address_records,
        skip_place_name=is_non_school_record_name,
    )
    records, duplicate_count = deduplicate_school_records(records)
    address_payload = {
        'stage': (
            'address_records'
            if not error_messages
            else 'address_records_incomplete'
        ),
        'city_context': validate_city_context(
            extraction_plan.get('city_context')
        ),
        'items': records,
        'metrics': {
            'source_count': engine_metrics['source_count'],
            'reviewed_source_count': engine_metrics[
                'reviewed_source_count'
            ],
            'skipped_source_count': engine_metrics[
                'skipped_source_count'
            ],
            'approved_rule_count': engine_metrics['approved_rule_count'],
            'item_count': len(records),
            'original_address_count': sum(
                bool(record['original_address']) for record in records
            ),
            'missing_original_address_count': sum(
                not record['original_address'] for record in records
            ),
            'missing_school_type_count': sum(
                not record['attributes']['school_type']
                for record in records
            ),
            'missing_school_nature_count': sum(
                not record['attributes']['school_nature']
                for record in records
            ),
            'duplicate_count': duplicate_count,
            'error_count': len(error_messages),
        },
        'errors': error_messages,
    }
    return address_payload, 1 if error_messages else 0


