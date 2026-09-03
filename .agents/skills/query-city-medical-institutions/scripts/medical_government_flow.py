"""医疗机构政府来源检查与提取薄层。"""

import argparse
import json
import sys
from pathlib import Path

from query_city_core.address.city import validate_city_context
from query_city_core.host_gate import (
    DEFAULT_HOST_MAX_WORKERS,
    DEFAULT_HOST_MIN_INTERVAL,
    DEFAULT_MAX_WORKERS,
)
from query_city_core.io_utils import write_json_payload
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
    AttributeTerm,
    FieldTerms,
    extract_government_records,
    inspect_government_source,
)
from query_city_core.official.readers import normalize_text

from medical_common import (
    build_medical_record,
    deduplicate_records,
    is_foreign_address_segment,
    split_address_segments,
)


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


GOVERNMENT_STAGE = 'medical_institutions_government_source'
PLAN_STAGE = 'medical_institutions_extraction_plan'

MEDICAL_FIELD_TERMS = FieldTerms(
    place_headers=('机构名称', '医疗机构名称'),
    exact_place_headers=('名称',),
    address_headers=('机构地址', '执业地址', '地址', '详细地址'),
    attribute_terms=(
        AttributeTerm(
            'administrative_unit',
            headers=('行政区划', '行政区', '所在区'),
        ),
        AttributeTerm(
            'institution_type',
            headers=('机构类别', '机构类型'),
        ),
        AttributeTerm(
            'institution_level',
            headers=('机构级别', '级别等级'),
        ),
        AttributeTerm(
            'license_no',
            headers=('登记号', '许可证号'),
        ),
    ),
    place_marker_pattern=(
        r'(?:医院|卫生院|诊所|门诊部|中心|站|实验室|口腔|医馆)'
    ),
    address_marker_pattern=r'(?:路|街|巷|大道|号|村|园区|社区|大厦|花园)',
    excluded_place_label_pattern=r'机构类别|机构级别|行政区划',
)


def normalize_source_items(source_manifest):
    """把医疗政府来源清单项转换为引擎使用的通用条目。"""
    city_context = validate_city_context(source_manifest.get('city_context'))
    administrative_unit = source_manifest.get('administrative_unit')
    if (
        not isinstance(administrative_unit, dict)
        or administrative_unit not in city_context.get('subdivisions')
    ):
        raise ValueError(
            'administrative_unit 必须原样来自 city_context.subdivisions'
        )
    sources = source_manifest.get('sources')
    if not isinstance(sources, list):
        raise ValueError('sources 必须是数组')
    items = []
    for source in sources:
        if str(source.get('status') or '') != 'ready':
            continue
        local_file = str(source.get('local_file') or '').strip()
        if not local_file:
            raise ValueError(f'{source.get("source_id")} 缺少 local_file')
        items.append({
            **source,
            'source_title': str(source.get('source_id') or ''),
            'publisher': str(source.get('authority') or ''),
            'publication_date': str(source.get('snapshot_date') or ''),
            'landing_page_url': str(source.get('url') or ''),
            'content_url': str(source.get('url') or ''),
            'local_files': [local_file],
            'local_file_urls': {local_file: str(source.get('url') or '')},
        })
    return city_context, administrative_unit, items


def _object_attribute_field(field, keys):
    """构造医疗对象列表规则的中性属性字段。"""
    return {
        'field': field,
        'keys': list(keys or []),
        'value': '',
        'column': None,
        'selector': '',
        'labels': [],
    }


def decorate_medical_rules(source_item, inspected_files, extraction_rules):
    """为工作簿/网页内嵌/查询结果补充对象列表规则。"""
    source_type = str(source_item.get('source_type') or '')
    local_files = source_item.get('local_files') or []
    file_name = local_files[0] if local_files else ''
    if source_type == 'xlsx_attachment':
        return
    if source_type == 'embedded_html_list':
        record_kind = str(source_item.get('record_kind') or 'license_list')
        address_keys = (
            ['jgdz'] if record_kind == 'community_health_center' else ['dz']
        )
        rule = {
            'file': file_name,
            'kind': 'object_list',
            'object_format': 'html_object_literal',
            'marker_keys': ['jgmc', 'docurl'],
            'container_keys': [],
            'place_name_keys': ['jgmc'],
            'original_address_keys': address_keys,
            'attribute_fields': [
                _object_attribute_field(
                    'administrative_unit',
                    ['xzqh'] if record_kind != 'community_health_center'
                    else ['dq'],
                ),
                _object_attribute_field(
                    'institution_type',
                    [],
                ),
                _object_attribute_field(
                    'institution_level',
                    ['jb'] if record_kind == 'license_list' else [],
                ),
            ],
            'approved': False,
        }
    elif source_type == 'html_card_list':
        rule = {
            'file': file_name,
            'kind': 'object_list',
            'object_format': 'html_js_assignment',
            'assignment_id_prefix': 'one_',
            'place_name_keys': ['yymc'],
            'original_address_keys': ['xxdz'],
            'attribute_fields': [
                _object_attribute_field(
                    'administrative_unit',
                    ['szq'],
                ),
                _object_attribute_field('institution_type', []),
                _object_attribute_field('institution_level', ['jb']),
            ],
            'approved': False,
        }
    elif source_type == 'query_page':
        rule = {
            'file': file_name,
            'kind': 'object_list',
            'object_format': 'jsonp',
            'place_name_keys': ['yymc', 'jgmc'],
            'original_address_keys': ['yydz', 'jgdz'],
            'attribute_fields': [
                _object_attribute_field('administrative_unit', ['szq']),
                _object_attribute_field('institution_type', ['yytype']),
                _object_attribute_field('institution_level', ['jb']),
            ],
            'approved': False,
        }
    else:
        return
    extraction_rules.append(rule)


def build_medical_extraction_plan(sources_path, plan_path):
    """调用公共检查引擎生成待复核提取计划。"""
    sources_path = Path(sources_path).resolve()
    manifest = json.loads(sources_path.read_text(encoding='utf-8'))
    if manifest.get('stage') != GOVERNMENT_STAGE:
        raise ValueError(f'stage 必须是 {GOVERNMENT_STAGE}')
    return inspect_government_source(
        sources_path,
        Path(plan_path).resolve(),
        MEDICAL_FIELD_TERMS,
        plan_stage=PLAN_STAGE,
        validate_manifest=normalize_source_items,
        decorate_source_plan=decorate_medical_rules,
    )


def _build_empty_medical_record(
    raw_item, source_item, attributes, city_context, fallback_unit
):
    """构造一条保留官方原文缺失的空地址记录。"""
    return build_medical_record(
        source_id=str(source_item.get('source_id') or ''),
        place_name=raw_item.get('place_name'),
        address_segment='',
        source_row=str(raw_item.get('row') or ''),
        source_reference=str(raw_item.get('source_reference') or ''),
        city_context=city_context,
        administrative_unit=fallback_unit,
        institution_type=attributes.get('institution_type'),
        institution_level=attributes.get('institution_level'),
        license_no=attributes.get('license_no'),
        source_authority=str(source_item.get('authority') or ''),
        snapshot_date=str(source_item.get('snapshot_date') or ''),
        merge_priority=int(source_item.get('priority') or 10),
    )


def build_address_records(
    raw_item,
    city_context=None,
    counters=None,
    target_administrative_unit='',
):
    """把中性原始提取记录拆成公共地址记录。"""
    source_item = raw_item.get('source_item') or {}
    attributes = raw_item.get('attributes') or {}
    city_context = city_context or source_item.get('_city_context') or {}
    if counters is None:
        counters = {}
    target_administrative_unit = str(
        target_administrative_unit or ''
    ).strip()
    source_administrative_unit = str(
        attributes.get('administrative_unit') or ''
    ).strip()
    if (
        target_administrative_unit
        and source_administrative_unit
        and source_administrative_unit != target_administrative_unit
    ):
        counters['skipped_out_of_scope_count'] = (
            counters.get('skipped_out_of_scope_count', 0) + 1
        )
        return []
    fallback_unit = target_administrative_unit or source_administrative_unit
    original_address = str(raw_item.get('original_address') or '').strip()
    if not original_address:
        return [_build_empty_medical_record(
            raw_item, source_item, attributes, city_context, fallback_unit
        )]
    segments = split_address_segments(original_address)
    if not segments:
        return [_build_empty_medical_record(
            raw_item, source_item, attributes, city_context, fallback_unit
        )]
    base_reference = str(raw_item.get('source_reference') or '')
    references = [
        f'{base_reference} | 地址 {index}'
        if len(segments) > 1
        else base_reference
        for index in range(1, len(segments) + 1)
    ]
    foreign_phrases = tuple(
        str(phrase or '').strip()
        for phrase in (source_item.get('foreign_phrases') or [])
    )
    records = []
    for segment_index, segment in enumerate(segments):
        if is_foreign_address_segment(
            segment, city_context, foreign_phrases
        ):
            counters['removed_foreign_count'] = (
                counters.get('removed_foreign_count', 0) + 1
            )
            continue
        records.append(build_medical_record(
            source_id=str(source_item.get('source_id') or ''),
            place_name=raw_item.get('place_name'),
            address_segment=segment,
            source_row=str(raw_item.get('row') or ''),
            source_reference=references[segment_index],
            city_context=city_context,
            administrative_unit=fallback_unit,
            license_administrative_unit=(
                source_administrative_unit or fallback_unit
            ),
            institution_type=attributes.get('institution_type'),
            institution_level=attributes.get('institution_level'),
            license_no=attributes.get('license_no'),
            source_authority=str(source_item.get('authority') or ''),
            snapshot_date=str(source_item.get('snapshot_date') or ''),
            merge_priority=int(source_item.get('priority') or 10),
        ))
    return records


def extract_medical_records(plan_path, output_path):
    """调用公共提取引擎、跨来源去重并输出地址记录。"""
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    if plan.get('stage') != PLAN_STAGE:
        raise ValueError(f'stage 必须是 {PLAN_STAGE}')
    city_context = validate_city_context(plan.get('city_context'))
    target_administrative_unit = normalize_text(
        (plan.get('administrative_unit') or {}).get('name')
    )
    for source_plan in plan.get('items') or []:
        source_plan['_city_context'] = city_context
    counters = {
        'removed_foreign_count': 0,
        'skipped_out_of_scope_count': 0,
    }

    def build_district_address_records(raw_item):
        """按当前行政单位目录构造拆分后的地址记录。"""
        return build_address_records(
            raw_item,
            city_context,
            counters,
            target_administrative_unit,
        )

    records, engine_metrics, error_messages = extract_government_records(
        Path(plan_path).resolve(),
        plan_stage=PLAN_STAGE,
        terms=MEDICAL_FIELD_TERMS,
        build_address_records=build_district_address_records,
    )
    unique_records = deduplicate_records(records)
    duplicate_count = len(records) - len(unique_records)
    items = [
        {
            key: value
            for key, value in record.items()
            if key != '_merge_priority'
        }
        for record in unique_records
    ]
    payload = {
        'stage': (
            'address_records' if not error_messages
            else 'address_records_incomplete'
        ),
        'city_context': city_context,
        'items': items,
        'metrics': {
            'source_count': engine_metrics['source_count'],
            'reviewed_source_count': engine_metrics[
                'reviewed_source_count'
            ],
            'skipped_source_count': engine_metrics[
                'skipped_source_count'
            ],
            'approved_rule_count': engine_metrics['approved_rule_count'],
            'raw_item_count': engine_metrics['raw_item_count'],
            'record_count': len(unique_records),
            'duplicate_count': duplicate_count,
            'removed_foreign_segment_count': counters.get(
                'removed_foreign_count', 0
            ),
            'skipped_out_of_scope_count': counters.get(
                'skipped_out_of_scope_count', 0
            ),
            'original_address_count': sum(
                bool(record['original_address'])
                for record in items
            ),
            'missing_original_address_count': sum(
                not record['original_address']
                for record in items
            ),
            'error_count': len(error_messages),
        },
        'errors': error_messages,
    }
    write_json_payload(output_path, payload)
    return payload


def build_argument_parser():
    """创建医疗机构政府来源处理命令解析器。"""
    parser = argparse.ArgumentParser(
        description='医疗机构政府来源通用检查与提取'
    )
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
    list_links_command.add_argument('--input', required=True)
    list_links_command.add_argument('--output', required=True)
    add_fetch_arguments(list_links_command)
    download_command = commands.add_parser(
        'download', help='保存已选定的政府来源文件'
    )
    download_command.add_argument('--manifest', required=True)
    download_command.add_argument('--output-dir', required=True)
    add_fetch_arguments(download_command)
    collect_command = commands.add_parser(
        'collect-details', help='保存名录链接的同构 HTML 详情页'
    )
    collect_command.add_argument('--input', required=True)
    collect_command.add_argument('--link-selector', required=True)
    collect_command.add_argument('--output-dir', required=True)
    collect_command.add_argument('--manifest', required=True)
    collect_command.add_argument('--allowed-domain', default='')
    add_fetch_arguments(collect_command)
    inspect_command = commands.add_parser('inspect', help='生成提取计划')
    inspect_command.add_argument('--sources', required=True)
    inspect_command.add_argument('--output', required=True)
    extract_command = commands.add_parser('extract', help='执行已复核计划')
    extract_command.add_argument('--plan', required=True)
    extract_command.add_argument('--output', required=True)
    return parser


def main() -> int:
    """执行来源采集、检查或提取命令。"""
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
                print(
                    f"抓取错误 {len(output_payload.get('errors') or [])} 条，"
                    '详见输出 errors 字段',
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
                print(
                    f"下载错误 {len(output_payload.get('errors') or [])} 条，"
                    '详见清单 errors 字段',
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
                print(
                    f"下载错误 {len(output_payload.get('errors') or [])} 条，"
                    '详见清单 errors 字段',
                    file=sys.stderr,
                )
            return exit_code
        output_path = Path(arguments.output).resolve()
        if arguments.command == 'inspect':
            output_payload, exit_code = build_medical_extraction_plan(
                Path(arguments.sources).resolve(), output_path
            )
            write_json_payload(output_path, output_payload)
        else:
            output_payload = extract_medical_records(
                Path(arguments.plan).resolve(), output_path
            )
            exit_code = 1 if output_payload.get('errors') else 0
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
