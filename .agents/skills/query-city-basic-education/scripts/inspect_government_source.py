"""检查政府学校名录并生成待复核的提取计划。"""

import os
from collections import Counter
from pathlib import Path
from typing import Any

from query_city_core.address.city import validate_city_context
from query_city_core.io_utils import read_json_payload
from query_city_core.official.extract import (
    AttributeTerm,
    FieldTerms,
    collect_repeated_html_candidates as _collect_repeated_html_candidates,
    consolidate_html_key_value_rules,
    inspect_government_source as _inspect_government_source,
    infer_html_key_value_rule as _infer_html_key_value_rule,
    infer_table_rule as _infer_table_rule,
    inspect_source_file as _inspect_source_file,
    read_table_cell,
    resolve_source_path,
)
from query_city_core.official.readers import normalize_text


PLACE_HEADERS = ('学校名称', '幼儿园名称', '园所名称', '机构名称', '校名')
EXACT_PLACE_HEADERS = ('学校', '名称')
ADDRESS_HEADERS = (
    '学校地址', '办学地址', '园区地址', '园所地址',
    '详细地址', '校址', '地址',
)
SCHOOL_TYPE_HEADERS = (
    '学校类型', '办学类型', '办学层次', '主体学校办学类型名称',
)
SCHOOL_NATURE_HEADERS = ('学校性质', '办学性质', '办园性质')
SOURCE_MANIFEST_STAGE = 'basic_education_government_source'
SOURCE_PROCESSING_STATUSES = {
    'completed', 'partial', 'no_official_source', 'source_unusable'
}
SOURCE_COVERAGE_STATUSES = {
    'covered', 'partial', 'no_official_source', 'source_unusable'
}
REQUIRED_SCHOOL_TYPE_COVERAGE = ('幼儿园', '小学', '初中', '高中')
SOURCE_MANIFEST_FIELDS = {
    'stage',
    'city_context',
    'administrative_unit',
    'processing_status',
    'school_type_coverage',
    'items',
}
SOURCE_ITEM_FIELDS = {
    'source_title',
    'publisher',
    'publication_date',
    'landing_page_url',
    'content_url',
    'covered_school_types',
    'contains_address',
    'local_files',
    'local_file_urls',
    'derived_files',
}
REQUIRED_SOURCE_ITEM_FIELDS = SOURCE_ITEM_FIELDS - {
    'derived_files', 'local_file_urls'
}

SCHOOL_FIELD_TERMS = FieldTerms(
    place_headers=PLACE_HEADERS,
    exact_place_headers=EXACT_PLACE_HEADERS,
    address_headers=ADDRESS_HEADERS,
    attribute_terms=(
        AttributeTerm(
            'school_type',
            headers=SCHOOL_TYPE_HEADERS,
            label_text='学校类别',
        ),
        AttributeTerm(
            'school_nature',
            headers=SCHOOL_NATURE_HEADERS,
            label_text='学校性质',
            fill_down=True,
        ),
    ),
    place_marker_pattern=r'(?:学校|幼儿园|小学|中学|校区|教学点)',
    address_marker_pattern=r'(?:路|街|巷|大道|公路|村|号|园区|镇|区|县)',
    excluded_place_label_pattern=r'学校类别|学校性质|上级主管部门',
)


def is_place_name_header(header_text: str) -> bool:
    """判断单元格是否为学校名称表头。"""
    return SCHOOL_FIELD_TERMS.is_place_header(header_text)


def is_address_header(header_text: str) -> bool:
    """判断单元格是否为地址表头。"""
    return SCHOOL_FIELD_TERMS.is_address_header(header_text)


def is_school_type_header(header_text: str) -> bool:
    """判断单元格是否为学校类型表头。"""
    return SCHOOL_FIELD_TERMS.attribute_field_matches_header(
        'school_type', header_text
    )


def is_school_nature_header(header_text: str) -> bool:
    """判断单元格是否为学校办学性质表头。"""
    return SCHOOL_FIELD_TERMS.attribute_field_matches_header(
        'school_nature', header_text
    )


def infer_table_rule(
    table_rows: list[list[str]],
    file_name: str,
    structure_kind: str,
    location: dict[str, Any],
) -> dict[str, Any] | None:
    """按学校表头词表生成待复核规则。"""
    return _infer_table_rule(
        table_rows, file_name, structure_kind, location, SCHOOL_FIELD_TERMS
    )


def infer_html_key_value_rule(
    table_rows: list[list[str]], file_name: str
) -> dict[str, Any] | None:
    """识别学校详情页中纵向排列的字段和值。"""
    return _infer_html_key_value_rule(
        table_rows, file_name, SCHOOL_FIELD_TERMS
    )


def collect_repeated_html_candidates(
    source_path: Path, file_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """检查网页或 Word 中重复的学校地址容器。"""
    return _collect_repeated_html_candidates(
        source_path, file_name, SCHOOL_FIELD_TERMS
    )


def inspect_source_file(
    source_path: Path, file_name: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """检查一个来源文件并生成规则建议。"""
    return _inspect_source_file(source_path, file_name, SCHOOL_FIELD_TERMS)


def validate_source_manifest(
    source_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """校验行政单位来源清单并返回公共处理所需字段。"""
    if source_manifest.get('stage') != SOURCE_MANIFEST_STAGE:
        raise ValueError(f'stage 必须是 {SOURCE_MANIFEST_STAGE}')
    unexpected_fields = set(source_manifest) - SOURCE_MANIFEST_FIELDS
    if unexpected_fields:
        raise ValueError(
            'government_source.json 包含未登记字段：'
            + '、'.join(sorted(unexpected_fields))
        )

    city_context = validate_city_context(source_manifest.get('city_context'))
    administrative_unit = source_manifest.get('administrative_unit')
    if (
        not isinstance(administrative_unit, dict)
        or administrative_unit not in city_context['subdivisions']
    ):
        raise ValueError(
            'administrative_unit 必须原样来自 city_context.subdivisions'
        )

    processing_status = source_manifest.get('processing_status')
    if processing_status not in SOURCE_PROCESSING_STATUSES:
        raise ValueError('processing_status 不在允许范围内')

    school_type_coverage = source_manifest.get('school_type_coverage')
    if not isinstance(school_type_coverage, dict):
        raise ValueError('school_type_coverage 必须是对象')
    for school_type in REQUIRED_SCHOOL_TYPE_COVERAGE:
        if school_type not in school_type_coverage:
            raise ValueError(f'school_type_coverage 缺少 {school_type}')
    for school_type, coverage_status in school_type_coverage.items():
        if not str(school_type or '').strip():
            raise ValueError('school_type_coverage 包含空学校类型')
        if coverage_status not in SOURCE_COVERAGE_STATUSES:
            raise ValueError(
                f'school_type_coverage.{school_type} 不在允许范围内'
            )

    source_items = source_manifest.get('items')
    if not isinstance(source_items, list):
        raise ValueError('items 必须是数组')
    for source_index, source_item in enumerate(source_items, start=1):
        if not isinstance(source_item, dict):
            raise ValueError('items 中的每项必须是对象')
        missing_fields = REQUIRED_SOURCE_ITEM_FIELDS - set(source_item)
        if missing_fields:
            raise ValueError(
                f'items[{source_index}] 缺少字段：'
                + '、'.join(sorted(missing_fields))
            )
        unexpected_item_fields = set(source_item) - SOURCE_ITEM_FIELDS
        if unexpected_item_fields:
            raise ValueError(
                f'items[{source_index}] 包含未登记字段：'
                + '、'.join(sorted(unexpected_item_fields))
            )
        for field_name in (
            'source_title',
            'publisher',
            'landing_page_url',
            'content_url',
        ):
            if not isinstance(source_item[field_name], str) or not (
                source_item[field_name].strip()
            ):
                raise ValueError(
                    f'items[{source_index}].{field_name} 必须是非空字符串'
                )
        publication_date = source_item['publication_date']
        if not isinstance(publication_date, str):
            raise ValueError(
                f'items[{source_index}].publication_date 必须是字符串'
            )
        covered_school_types = source_item['covered_school_types']
        if (
            not isinstance(covered_school_types, list)
            or not covered_school_types
            or any(
                not isinstance(school_type, str) or not school_type.strip()
                for school_type in covered_school_types
            )
        ):
            raise ValueError(
                f'items[{source_index}].covered_school_types '
                '必须是非空字符串数组'
            )
        if not isinstance(source_item['contains_address'], bool):
            raise ValueError(
                f'items[{source_index}].contains_address 必须是布尔值'
            )
        for field_name, allow_empty in (
            ('local_files', False), ('derived_files', True)
        ):
            file_names = source_item.get(field_name, [])
            if (
                not isinstance(file_names, list)
                or (not allow_empty and not file_names)
                or any(
                    not isinstance(file_name, str) or not file_name.strip()
                    for file_name in file_names
                )
            ):
                raise ValueError(
                    f'items[{source_index}].{field_name} '
                    + ('必须是字符串数组' if allow_empty else '必须是非空字符串数组')
                )
        local_file_urls = source_item.get('local_file_urls') or {}
        if (
            not isinstance(local_file_urls, dict)
            or any(
                not isinstance(file_name, str)
                or file_name not in source_item['local_files']
                or not isinstance(source_url, str)
                or not source_url.strip()
                for file_name, source_url in local_file_urls.items()
            )
        ):
            raise ValueError(
                f'items[{source_index}].local_file_urls '
                '必须把 local_files 中的文件名映射到非空网址'
            )

    required_coverage = [
        school_type_coverage[school_type]
        for school_type in REQUIRED_SCHOOL_TYPE_COVERAGE
    ]
    if processing_status == 'completed':
        if not source_items or any(
            coverage_status != 'covered'
            for coverage_status in required_coverage
        ):
            raise ValueError(
                'processing_status 为 completed 时，items 必须非空且四类学校均为 covered'
            )
    elif processing_status == 'partial':
        if not source_items or all(
            coverage_status == 'covered'
            for coverage_status in required_coverage
        ):
            raise ValueError(
                'processing_status 为 partial 时，items 必须非空且四类学校存在覆盖缺口'
            )
    elif processing_status == 'no_official_source':
        if source_items or any(
            coverage_status != 'no_official_source'
            for coverage_status in required_coverage
        ):
            raise ValueError(
                'processing_status 为 no_official_source 时，items 必须为空且四类学校状态一致'
            )
    elif (
        source_items
        or 'source_unusable' not in required_coverage
        or any(
            coverage_status not in {'no_official_source', 'source_unusable'}
            for coverage_status in required_coverage
        )
    ):
        raise ValueError(
            'processing_status 为 source_unusable 时，items 必须为空且至少一类学校来源不可用'
        )
    return city_context, administrative_unit, source_items


def build_extraction_plan(
    input_path: Path, output_path: Path
) -> tuple[dict[str, Any], int]:
    """调用公共政府来源检查引擎生成提取计划。"""

    def decorate_source_plan(
        source_item,
        inspected_files,
        extraction_rules,
    ):
        covered_school_types = source_item.get(
            'covered_school_types'
        ) or []
        if len(covered_school_types) != 1:
            return
        suggested_school_type = normalize_text(covered_school_types[0])
        for extraction_rule in extraction_rules:
            for attribute_field in extraction_rule.get(
                'attribute_fields', []
            ):
                if (
                    attribute_field.get('field') == 'school_type'
                    and not attribute_field.get('value')
                    and not attribute_field.get('column')
                    and not attribute_field.get('selector')
                    and not attribute_field.get('labels')
                ):
                    attribute_field['value'] = suggested_school_type

    return _inspect_government_source(
        Path(input_path).resolve(),
        Path(output_path).resolve(),
        SCHOOL_FIELD_TERMS,
        plan_stage='basic_education_extraction_plan',
        validate_manifest=validate_source_manifest,
        inspect_source_file=inspect_source_file,
        decorate_source_plan=decorate_source_plan,
    )
