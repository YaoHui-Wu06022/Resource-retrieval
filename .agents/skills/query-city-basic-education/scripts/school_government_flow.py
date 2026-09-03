"""基础教育政府来源检查与提取薄层。"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from query_city_core.address.city import validate_city_context
from query_city_core.host_gate import (
    DEFAULT_HOST_MAX_WORKERS,
    DEFAULT_HOST_MIN_INTERVAL,
    DEFAULT_MAX_WORKERS,
)
from query_city_core.io_utils import read_json_payload, write_json_payload
from query_city_core.official.collectors.directory_links import (
    collect_directory_links,
)
from query_city_core.official.collectors.linked_pages import (
    collect_linked_html_pages,
)
from query_city_core.official.collectors.source_files import (
    download_source_files,
)
from query_city_core.official.extract import (
    collect_repeated_html_candidates as _collect_repeated_html_candidates,
    extract_government_records,
    infer_html_key_value_rule as _infer_html_key_value_rule,
    infer_table_rule as _infer_table_rule,
    inspect_government_source as _inspect_government_source,
)
from query_city_core.official.readers import (
    load_source_tables,
    normalize_text,
)

from school_common import (
    SCHOOL_FIELD_TERMS,
    build_records_for_locations,
    deduplicate_school_records,
    fill_missing_school_type_from_siblings,
    fill_missing_original_address_from_siblings,
    infer_school_type_from_name_marker,
    infer_school_type_from_stage_name,
    is_non_school_record_name,
)


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
    'source_form_reason',
}
REQUIRED_SOURCE_ITEM_FIELDS = SOURCE_ITEM_FIELDS - {
    'derived_files', 'local_file_urls', 'source_form_reason'
}


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
        source_form_reason = source_item.get('source_form_reason')
        if (
            source_form_reason is not None
            and source_form_reason != 'no_text_alternative'
        ):
            raise ValueError(
                f'items[{source_index}].source_form_reason '
                '仅允许 no_text_alternative'
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
        decorate_source_plan=decorate_source_plan,
    )


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
    records = fill_missing_school_type_from_siblings(records)
    records = fill_missing_original_address_from_siblings(records)
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


def read_preview_table_cell(table_row: list[str], column_index: int) -> str:
    """读取复核用表格单元格文本，越界返回空串。"""
    if column_index < 1 or column_index > len(table_row):
        return ''
    return normalize_text(table_row[column_index - 1])


def preview_extraction_plan(plan_path: Path) -> tuple[dict[str, Any], int]:
    """复核提取计划的行覆盖、重叠与类型分布。"""
    extraction_plan = read_json_payload(plan_path)
    if extraction_plan.get('stage') != 'basic_education_extraction_plan':
        raise ValueError('输入必须是 basic_education_extraction_plan JSON')
    plan_dir = Path(plan_path).resolve().parent
    file_reports = []
    total_candidates = 0
    total_covered = 0
    total_uncovered = 0
    total_overlaps = 0
    approved_rule_count = 0
    pending_rule_count = 0
    type_counts: dict[str, int] = {}
    preview_errors = []
    for source_item in extraction_plan.get('items') or []:
        file_names = list(source_item.get('local_files') or []) + list(
            source_item.get('derived_files') or []
        )
        for file_name in file_names:
            file_rules = [
                rule
                for rule in source_item.get('extraction_rules') or []
                if rule.get('file') == file_name
            ]
            approved_rules = [
                rule for rule in file_rules if rule.get('approved') is True
            ]
            approved_rule_count += len(approved_rules)
            pending_rule_count += len(file_rules) - len(approved_rules)
            file_report = {
                'file': file_name,
                'candidate_row_count': 0,
                'covered_row_count': 0,
                'uncovered_rows': [],
                'overlap_rows': [],
            }
            if not approved_rules:
                paired_vision_name = f'{file_name}.vision.json'
                paired_vision_approved = any(
                    rule.get('file') == paired_vision_name
                    and rule.get('approved') is True
                    and rule.get('kind') == 'vision_table'
                    for rule in source_item.get('extraction_rules') or []
                )
                if paired_vision_approved:
                    file_report['skipped_reason'] = (
                        '原图由派生 vision.json 规则覆盖'
                    )
                    file_reports.append(file_report)
                    continue
            try:
                source_path = plan_dir / file_name
                tables, _metadata = load_source_tables(source_path)
            except Exception as exc:
                error_message = normalize_text(exc)
                file_report['error'] = error_message
                preview_errors.append(
                    f'{file_name} 读取失败：{error_message}'
                )
                file_reports.append(file_report)
                continue
            if not approved_rules:
                file_report['error'] = '没有已批准的表格提取规则'
                preview_errors.append(f'{file_name} 没有已批准的表格提取规则')
                file_reports.append(file_report)
                continue
            table_rules = []
            for rule in approved_rules:
                if rule.get('kind') not in {
                    'table', 'sheet', 'pdf_table', 'vision_table'
                }:
                    continue
                table = next(
                    (
                        structure
                        for structure in tables
                        if structure.get('kind') == rule.get('kind')
                        and structure.get('location') == rule.get('location')
                    ),
                    None,
                )
                if table is None:
                    preview_errors.append(
                        f'{file_name} 未找到规则定位的表格'
                    )
                    continue
                table_rows = table.get('rows') or []
                start_row = rule.get('data_start_row') or 1
                end_row = rule.get('data_end_row') or len(table_rows)
                if not rule.get('place_name_columns'):
                    preview_errors.append(
                        f'{file_name} 规则缺少 place_name_columns'
                    )
                    continue
                table_rules.append((
                    rule, table_rows, start_row, end_row,
                ))
            if not table_rules:
                file_report['error'] = '没有可用的表格提取规则'
                preview_errors.append(f'{file_name} 没有可用的表格提取规则')
                file_reports.append(file_report)
                continue
            global_start_row = min(
                start_row for _rule, _rows, start_row, _end in table_rules
            )
            global_end_row = max(
                end_row for _rule, _rows, _start, end_row in table_rules
            )
            first_table_rows = table_rules[0][1]
            candidate_rows: dict[int, str] = {}
            for row_number in range(
                global_start_row,
                min(global_end_row, len(first_table_rows)) + 1,
            ):
                table_row = list(first_table_rows[row_number - 1])
                name_parts = [
                    read_preview_table_cell(
                        table_row, column_index
                    )
                    for column_index in table_rules[0][0].get(
                        'place_name_columns'
                    )
                ]
                place_name = ''.join(
                    part for part in name_parts if part
                )
                if not place_name or any(
                    SCHOOL_FIELD_TERMS.is_place_header(part)
                    for part in name_parts
                ) or is_non_school_record_name(place_name):
                    continue
                candidate_rows[row_number] = place_name
            row_rule_count: dict[int, int] = {}
            row_types: dict[int, list[str]] = {}
            covered_rows: set[int] = set()
            for rule, table_rows, start_row, end_row in table_rules:
                excluded_rows = set(rule.get('exclude_rows') or [])
                type_attributes = [
                    attribute
                    for attribute in rule.get('attribute_fields') or []
                    if attribute.get('field') == 'school_type'
                ]
                for row_number in range(
                    start_row, min(end_row, len(table_rows)) + 1
                ):
                    if (
                        row_number not in candidate_rows
                        or row_number in excluded_rows
                    ):
                        continue
                    covered_rows.add(row_number)
                    row_rule_count[row_number] = (
                        row_rule_count.get(row_number, 0) + 1
                    )
                    table_row = list(table_rows[row_number - 1])
                    place_name = candidate_rows[row_number]
                    rule_type = ''
                    for attribute in type_attributes:
                        if attribute.get('column') is not None:
                            rule_type = read_preview_table_cell(
                                table_row, attribute.get('column')
                            )
                        else:
                            rule_type = normalize_text(
                                attribute.get('value')
                            )
                        if rule_type:
                            break
                    row_types.setdefault(row_number, []).append(
                        (
                            infer_school_type_from_stage_name(place_name)
                            or infer_school_type_from_name_marker(place_name)
                            or rule_type
                        )
                    )
            uncovered_rows = sorted(
                row_number
                for row_number, _place_name in candidate_rows.items()
                if row_number not in covered_rows
            )
            overlap_rows = sorted(
                row_number
                for row_number, hit_count in row_rule_count.items()
                if hit_count > 1
            )
            file_report['candidate_row_count'] = len(candidate_rows)
            file_report['covered_row_count'] = len(covered_rows)
            file_report['uncovered_rows'] = uncovered_rows
            file_report['overlap_rows'] = overlap_rows
            for row_number, rule_types in row_types.items():
                for school_type in dict.fromkeys(rule_types):
                    if school_type:
                        type_counts[school_type] = (
                            type_counts.get(school_type, 0) + 1
                        )
            total_candidates += len(candidate_rows)
            total_covered += len(covered_rows)
            total_uncovered += len(uncovered_rows)
            total_overlaps += len(overlap_rows)
            file_reports.append(file_report)
    error_count = len(preview_errors)
    preview_payload = {
        'stage': 'extraction_plan_preview',
        'file_count': len(file_reports),
        'approved_rule_count': approved_rule_count,
        'pending_rule_count': pending_rule_count,
        'candidate_row_count': total_candidates,
        'covered_row_count': total_covered,
        'uncovered_row_count': total_uncovered,
        'overlap_row_count': total_overlaps,
        'type_counts': dict(
            sorted(type_counts.items(), key=lambda pair: -pair[1])
        ),
        'files': file_reports,
        'errors': preview_errors,
        'error_count': error_count,
    }
    has_issues = bool(
        total_uncovered
        or total_overlaps
        or pending_rule_count
        or error_count
    )
    return preview_payload, 1 if has_issues else 0


def build_argument_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description='检查并提取基础教育学校地址')
    commands = parser.add_subparsers(dest='command', required=True)

    def add_fetch_arguments(command_parser):
        """为抓取或下载命令添加并发与同域节流参数。"""
        command_parser.add_argument(
            '--max-workers',
            type=int,
            default=DEFAULT_MAX_WORKERS,
            help='进程内最大并发任务数',
        )
        command_parser.add_argument(
            '--host-max-workers',
            type=int,
            default=DEFAULT_HOST_MAX_WORKERS,
            help='同一主机最大并发数，0 表示不限制',
        )
        command_parser.add_argument(
            '--host-min-interval',
            type=float,
            default=DEFAULT_HOST_MIN_INTERVAL,
            help='同一主机两次请求的最小间隔秒数',
        )

    list_links_command = commands.add_parser(
        'list-links', help='抓取栏目页并列出文章链接'
    )
    list_links_command.add_argument('--input', required=True, help='目录页清单')
    list_links_command.add_argument('--output', required=True, help='链接输出路径')
    add_fetch_arguments(list_links_command)
    download_command = commands.add_parser(
        'download', help='保存已选定的政府来源文件'
    )
    download_command.add_argument(
        '--manifest', required=True, help='下载清单 JSON 路径'
    )
    download_command.add_argument(
        '--output-dir', required=True, help='行政单位目录'
    )
    add_fetch_arguments(download_command)
    inspect_command = commands.add_parser('inspect', help='生成提取计划')
    inspect_command.add_argument(
        '--sources', required=True, help='government_source.json 路径'
    )
    inspect_command.add_argument('--output', required=True, help='计划输出路径')
    preview_command = commands.add_parser(
        'preview', help='复核提取计划行覆盖与类型分布'
    )
    preview_command.add_argument(
        '--plan', required=True, help='提取计划路径'
    )
    collect_command = commands.add_parser(
        'collect-details', help='保存名录链接的同构 HTML 详情页'
    )
    collect_command.add_argument('--input', required=True, help='本地名录 HTML')
    collect_command.add_argument(
        '--link-selector', required=True, help='详情页链接 CSS 选择器'
    )
    collect_command.add_argument(
        '--output-dir', required=True, help='详情页保存目录'
    )
    collect_command.add_argument(
        '--manifest', required=True, help='详情页文件与网址清单'
    )
    collect_command.add_argument(
        '--allowed-domain', default='', help='允许下载的唯一域名'
    )
    add_fetch_arguments(collect_command)
    extract_command = commands.add_parser('extract', help='执行已复核计划')
    extract_command.add_argument('--plan', required=True, help='提取计划路径')
    extract_command.add_argument('--output', required=True, help='地址记录输出路径')
    return parser


def main() -> int:
    """执行来源检查或学校地址提取。"""
    arguments = build_argument_parser().parse_args()
    try:
        if arguments.command == 'list-links':
            output_payload, exit_code = collect_directory_links(
                Path(arguments.input).resolve(),
                Path(arguments.output).resolve(),
                arguments.max_workers,
                arguments.host_max_workers,
                arguments.host_min_interval,
            )
            print(json.dumps(output_payload['metrics'], ensure_ascii=False))
            if exit_code != 0:
                error_count = len(output_payload.get('errors') or [])
                print(
                    f'抓取错误 {error_count} 条，详见输出 errors 字段',
                    file=sys.stderr,
                )
            return exit_code
        if arguments.command == 'download':
            output_payload, exit_code = download_source_files(
                Path(arguments.manifest).resolve(),
                Path(arguments.output_dir).resolve(),
                arguments.max_workers,
                arguments.host_max_workers,
                arguments.host_min_interval,
            )
            print(json.dumps(output_payload['metrics'], ensure_ascii=False))
            if exit_code != 0:
                error_count = len(output_payload.get('errors') or [])
                print(
                    f'下载错误 {error_count} 条，详见清单 errors 字段',
                    file=sys.stderr,
                )
            return exit_code
        if arguments.command == 'collect-details':
            output_payload, exit_code = collect_linked_html_pages(
                Path(arguments.input).resolve(),
                arguments.link_selector,
                Path(arguments.output_dir).resolve(),
                Path(arguments.manifest).resolve(),
                arguments.allowed_domain,
                arguments.max_workers,
                arguments.host_max_workers,
                arguments.host_min_interval,
            )
            print(json.dumps(output_payload['metrics'], ensure_ascii=False))
            if exit_code != 0:
                error_count = len(output_payload.get('errors') or [])
                print(
                    f'下载错误 {error_count} 条，详见清单 errors 字段',
                    file=sys.stderr,
                )
            return exit_code
        if arguments.command == 'preview':
            output_payload, exit_code = preview_extraction_plan(
                Path(arguments.plan).resolve()
            )
            preview_summary = {
                key: value
                for key, value in output_payload.items()
                if key != 'files'
            }
            print(json.dumps(preview_summary, ensure_ascii=False))
            if exit_code != 0:
                issue_parts = [
                    f'缺行 {output_payload.get("uncovered_row_count", 0)}',
                    f'重叠 {output_payload.get("overlap_row_count", 0)}',
                    f'待批准 {output_payload.get("pending_rule_count", 0)}',
                    f'错误 {output_payload.get("error_count", 0)}',
                ]
                print(
                    '提取计划复核未通过：' + '、'.join(issue_parts),
                    file=sys.stderr,
                )
            return exit_code
        output_path = Path(arguments.output).resolve()
        if arguments.command == 'inspect':
            output_payload, exit_code = build_extraction_plan(
                Path(arguments.sources).resolve(), output_path
            )
        else:
            output_payload, exit_code = extract_school_records(
                Path(arguments.plan).resolve()
            )
        write_json_payload(output_path, output_payload)
        print(json.dumps(
            output_payload.get('inspection_summary')
            or output_payload.get('metrics'),
            ensure_ascii=False,
        ))
        return exit_code
    except Exception as exc:
        print(f'错误：{normalize_text(exc)}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
