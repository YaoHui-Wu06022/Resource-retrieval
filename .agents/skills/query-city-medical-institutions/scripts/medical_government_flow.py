"""医疗机构政府来源通用检查与提取薄层。"""

import argparse
import json
import sys
from pathlib import Path

from query_city_core.address.city import validate_city_context
from query_city_core.io_utils import write_json_payload
from query_city_core.official.extract import (
    AttributeTerm,
    FieldTerms,
    extract_government_records,
    inspect_government_source,
)

from medical_common import (
    build_medical_record,
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
    return city_context, None, items


def _object_attribute_field(field, keys):
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


def build_medical_extraction_plan(
    sources_path,
    plan_path,
):
    """调用公共检查引擎生成待复核提取计划。"""
    sources_path = Path(sources_path).resolve()
    manifest = json.loads(sources_path.read_text(encoding='utf-8'))
    if manifest.get('stage') != GOVERNMENT_STAGE:
        raise ValueError(f'stage 必须是 {GOVERNMENT_STAGE}')
    if not manifest.get('city_context'):
        city_context_path = sources_path.parent / 'city_context.json'
        if not city_context_path.is_file():
            raise ValueError('缺少 city_context 或同目录 city_context.json')
        manifest['city_context'] = json.loads(
            city_context_path.read_text(encoding='utf-8')
        )
    return inspect_government_source(
        sources_path,
        Path(plan_path).resolve(),
        MEDICAL_FIELD_TERMS,
        plan_stage=PLAN_STAGE,
        validate_manifest=normalize_source_items,
        decorate_source_plan=decorate_medical_rules,
    )


def build_address_records(raw_item, city_context=None):
    """把中性原始提取记录拆成公共地址记录。"""
    source_item = raw_item.get('source_item') or {}
    attributes = raw_item.get('attributes') or {}
    city_context = city_context or source_item.get('_city_context') or {}
    records = []
    source_reference = str(raw_item.get('source_reference') or '')
    original_address = str(raw_item.get('original_address') or '').strip()
    if not original_address:
        return [build_medical_record(
            source_id=str(source_item.get('source_id') or ''),
            place_name=raw_item.get('place_name'),
            address_segment='',
            source_row=str(raw_item.get('row') or ''),
            source_reference=source_reference,
            city_context=city_context,
            administrative_unit=attributes.get('administrative_unit'),
            institution_type=attributes.get('institution_type'),
            institution_level=attributes.get('institution_level'),
            license_no=attributes.get('license_no'),
            source_authority=str(source_item.get('authority') or ''),
            snapshot_date=str(source_item.get('snapshot_date') or ''),
            merge_priority=int(source_item.get('priority') or 10),
        )]
    foreign_phrases = tuple(
        str(phrase or '').strip()
        for phrase in (source_item.get('foreign_phrases') or [])
    )
    for address_index, segment in enumerate(
        split_address_segments(original_address),
        start=1,
    ):
        if is_foreign_address_segment(
            segment, city_context, foreign_phrases
        ):
            continue
        segments = split_address_segments(original_address)
        if len(segments) > 1:
            source_reference += f' | 地址 {address_index}'
        records.append(build_medical_record(
            source_id=str(source_item.get('source_id') or ''),
            place_name=raw_item.get('place_name'),
            address_segment=segment,
            source_row=str(raw_item.get('row') or ''),
            source_reference=source_reference,
            city_context=city_context,
            administrative_unit=attributes.get('administrative_unit'),
            institution_type=attributes.get('institution_type'),
            institution_level=attributes.get('institution_level'),
            license_no=attributes.get('license_no'),
            source_authority=str(source_item.get('authority') or ''),
            snapshot_date=str(source_item.get('snapshot_date') or ''),
            merge_priority=int(source_item.get('priority') or 10),
        ))
    return records


def extract_medical_records(plan_path, output_path):
    """调用公共提取引擎并输出地址记录。"""
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    if plan.get('stage') != PLAN_STAGE:
        raise ValueError(f'stage 必须是 {PLAN_STAGE}')
    city_context = validate_city_context(plan.get('city_context'))
    for source_plan in plan.get('items') or []:
        source_plan['_city_context'] = city_context
    records, metrics, errors = extract_government_records(
        Path(plan_path).resolve(),
        plan_stage=PLAN_STAGE,
        terms=MEDICAL_FIELD_TERMS,
        build_address_records=lambda raw_item: build_address_records(
            raw_item, city_context
        ),
    )
    payload = {
        'stage': (
            'address_records' if not errors else 'address_records_incomplete'
        ),
        'city_context': city_context,
        'items': records,
        'metrics': {
            **metrics,
            'original_address_count': sum(
                bool(record['original_address']) for record in records
            ),
            'missing_original_address_count': sum(
                not record['original_address'] for record in records
            ),
        },
        'errors': errors,
    }
    write_json_payload(output_path, payload)
    return payload


def main():
    """解析参数并执行 inspect 或 extract。"""
    parser = argparse.ArgumentParser(
        description='医疗机构政府来源通用检查与提取'
    )
    commands = parser.add_subparsers(dest='command', required=True)
    inspect_command = commands.add_parser('inspect')
    inspect_command.add_argument('--sources', required=True)
    inspect_command.add_argument('--output', required=True)
    extract_command = commands.add_parser('extract')
    extract_command.add_argument('--plan', required=True)
    extract_command.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'inspect':
            plan, exit_code = build_medical_extraction_plan(
                args.sources, args.output
            )
            write_json_payload(args.output, plan)
            print(json.dumps({'exit_code': exit_code}))
        else:
            payload = extract_medical_records(args.plan, args.output)
            print(json.dumps({
                'exit_code': 1 if payload.get('errors') else 0,
                **payload['metrics'],
            }, ensure_ascii=False))
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
