"""检查政府学校名录并生成待复核的提取计划。"""

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from source_readers import (
    detect_source_format,
    load_source_html,
    load_source_tables,
    normalize_text,
)
from query_city_core.city import validate_city_context


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
    'derived_files',
}
REQUIRED_SOURCE_ITEM_FIELDS = SOURCE_ITEM_FIELDS - {'derived_files'}


def read_json_object(json_path: Path) -> dict[str, Any]:
    """读取 UTF-8 JSON 对象。"""
    with json_path.open(encoding='utf-8') as stream:
        json_object = json.load(stream)
    if not isinstance(json_object, dict):
        raise ValueError(f'JSON 顶层必须是对象：{json_path}')
    return json_object


def write_json_object(json_path: Path, json_object: dict[str, Any]) -> None:
    """写入格式稳定的 UTF-8 JSON。"""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(json_object, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


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


def resolve_source_path(source_dir: Path, file_name: str) -> Path:
    """解析并限制来源文件位于来源目录内。"""
    source_path = (source_dir / file_name).resolve()
    try:
        source_path.relative_to(source_dir)
    except ValueError as exc:
        raise ValueError(f'来源文件越出来源目录：{file_name}') from exc
    if not source_path.is_file():
        raise FileNotFoundError(f'来源文件不存在：{file_name}')
    return source_path


def normalize_header(header_text: str) -> str:
    """统一表头文本以便匹配字段。"""
    return re.sub(
        r'[\s（）()：:、/\\_\-]+', '', normalize_text(header_text)
    ).lower()


def is_place_name_header(header_text: str) -> bool:
    """判断单元格是否为学校名称表头。"""
    header = normalize_header(header_text)
    return header in EXACT_PLACE_HEADERS or any(
        keyword in header for keyword in PLACE_HEADERS
    )


def is_address_header(header_text: str) -> bool:
    """判断单元格是否为地址表头。"""
    header = normalize_header(header_text)
    return any(keyword in header for keyword in ADDRESS_HEADERS)


def is_school_type_header(header_text: str) -> bool:
    """判断单元格是否为学校类型表头。"""
    header = normalize_header(header_text)
    return any(keyword in header for keyword in SCHOOL_TYPE_HEADERS)


def is_school_nature_header(header_text: str) -> bool:
    """判断单元格是否为学校办学性质表头。"""
    header = normalize_header(header_text)
    return any(keyword in header for keyword in SCHOOL_NATURE_HEADERS)


def read_table_cell(table_row: list[str], column_index: int | None) -> str:
    """按一基列号安全读取单元格。"""
    if column_index is None:
        return ''
    if not isinstance(column_index, int) or column_index < 1:
        raise ValueError('列号必须是从 1 开始的整数')
    return table_row[column_index - 1] if column_index <= len(table_row) else ''


def infer_table_rule(
    table_rows: list[list[str]],
    file_name: str,
    structure_kind: str,
    location: dict[str, Any],
) -> dict[str, Any] | None:
    """根据常见表头生成待复核规则。"""
    for header_index, header_row in enumerate(table_rows[:10], start=1):
        place_columns = [
            index for index, header_text in enumerate(header_row, start=1)
            if is_place_name_header(header_text)
        ]
        if not place_columns:
            continue
        address_columns = [
            index for index, header_text in enumerate(header_row, start=1)
            if is_address_header(header_text)
        ]
        school_type_columns = [
            index for index, header_text in enumerate(header_row, start=1)
            if is_school_type_header(header_text)
        ]
        school_nature_columns = [
            index for index, header_text in enumerate(header_row, start=1)
            if is_school_nature_header(header_text)
        ]
        fill_down_columns = []
        if address_columns and any(
            not read_table_cell(data_row, place_columns[0])
            and read_table_cell(data_row, address_columns[0])
            for data_row in table_rows[header_index:]
        ):
            fill_down_columns.append(place_columns[0])
        return {
            'file': file_name,
            'kind': structure_kind,
            'location': location,
            'header_row': header_index,
            'data_start_row': header_index + 1,
            'data_end_row': None,
            'place_name_columns': place_columns,
            'place_name_separator': '',
            'original_address_column': address_columns[0] if address_columns else None,
            'school_type_column': (
                school_type_columns[0] if school_type_columns else None
            ),
            'school_type_value': '',
            'school_nature_column': (
                school_nature_columns[0] if school_nature_columns else None
            ),
            'school_nature_value': '',
            'fill_down_columns': fill_down_columns,
            'required_cell_values': [],
            'exclude_rows': [],
            'approved': False,
        }
    return None


def collect_repeated_html_candidates(
    source_path: Path, file_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """检查网页或 Word 中重复的学校地址容器。"""
    from bs4 import BeautifulSoup
    from soupsieve import escape

    soup = BeautifulSoup(load_source_html(source_path), 'lxml')
    groups: dict[tuple[str, tuple[str, ...]], list[Any]] = defaultdict(list)
    for element in (soup.body or soup).find_all(True):
        classes = tuple(sorted(element.get('class') or []))
        if (
            not classes
            or element.name in {'script', 'style', 'table', 'tr', 'td', 'th'}
            or element.find_parent('table') is not None
        ):
            continue
        element_text = normalize_text(element.get_text(' ', strip=True))
        if 4 <= len(element_text) <= 300:
            groups[(element.name, classes)].append(element)
    repeated_blocks = []
    suggested_rules = []
    for (tag, classes), elements in groups.items():
        if len(elements) < 3:
            continue
        element_texts = [
            normalize_text(element.get_text(' ', strip=True))
            for element in elements
        ]
        repeated_blocks.append({
            'tag': tag,
            'classes': list(classes),
            'count': len(elements),
            'preview': element_texts[:3],
        })
        child_rows = [element.find_all(recursive=False) for element in elements[:8]]
        if not child_rows or min(map(len, child_rows)) < 2:
            continue
        column_count = min(map(len, child_rows))
        columns = [
            [
                normalize_text(row[index].get_text(' ', strip=True))
                for row in child_rows
            ]
            for index in range(column_count)
        ]
        place_scores = [
            sum(
                bool(re.search(
                    r'(?:学校|幼儿园|小学|中学|校区|教学点)', cell_text
                ))
                for cell_text in column
            )
            for column in columns
        ]
        address_scores = [
            sum(
                bool(re.search(
                    r'(?:路|街|巷|大道|公路|村|号|园区|镇|区|县)', cell_text
                ))
                for cell_text in column
            )
            for column in columns
        ]
        place_index = max(range(column_count), key=place_scores.__getitem__)
        address_index = max(range(column_count), key=address_scores.__getitem__)
        threshold = max(len(child_rows) // 2, 2)
        if (
            place_index == address_index
            or place_scores[place_index] < threshold
            or address_scores[address_index] < threshold
        ):
            continue
        suggested_rules.append({
            'file': file_name,
            'kind': 'html_css',
            'row_selector': tag + ''.join(f'.{escape(name)}' for name in classes),
            'place_name_selector': f':scope > :nth-child({place_index + 1})',
            'original_address_selector': f':scope > :nth-child({address_index + 1})',
            'school_type_selector': '',
            'school_type_value': '',
            'school_nature_selector': '',
            'school_nature_value': '',
            'exclude_rows': [],
            'approved': False,
        })
    repeated_blocks.sort(key=lambda block: block['count'], reverse=True)
    text_preview = normalize_text(
        (soup.body or soup).get_text(' ', strip=True)
    )[:800]
    return repeated_blocks[:15], suggested_rules, text_preview


def inspect_source_file(
    source_path: Path, file_name: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """检查一个来源文件并生成规则建议。"""
    tables, inspection_metadata = load_source_tables(source_path)
    structures = []
    suggested_rules = []
    for table in tables:
        rows = table['rows']
        structures.append({
            'kind': table['kind'],
            'location': table['location'],
            'row_count': len(rows),
            'column_count': max((len(row) for row in rows), default=0),
            'preview_rows': rows[:8],
        })
        suggested_rule = infer_table_rule(
            rows, file_name, table['kind'], table['location']
        )
        if suggested_rule:
            suggested_rules.append(suggested_rule)
    repeated_blocks = []
    text_preview = ''
    if detect_source_format(source_path) == 'html':
        repeated_blocks, repeated_rules, text_preview = (
            collect_repeated_html_candidates(source_path, file_name)
        )
        suggested_rules.extend(repeated_rules)
        if (
            repeated_rules
            and inspection_metadata['inspection_status'] == 'manual_review'
        ):
            inspection_metadata['inspection_status'] = 'ready'
    return ({
        'file': file_name,
        'format': source_path.suffix.lower().lstrip('.'),
        'size_bytes': source_path.stat().st_size,
        **inspection_metadata,
        'structures': structures,
        'repeated_blocks': repeated_blocks,
        'text_preview': text_preview,
    }, suggested_rules)


def build_extraction_plan(
    input_path: Path, output_path: Path
) -> tuple[dict[str, Any], int]:
    """检查来源清单并生成提取计划。"""
    source_manifest = read_json_object(input_path)
    city_context, administrative_unit, source_items = validate_source_manifest(
        source_manifest
    )
    source_dir = input_path.parent.resolve()
    source_plans = []
    status_counts: Counter[str] = Counter()
    error_count = 0
    for source in source_items:
        local_files = source.get('local_files')
        if not isinstance(local_files, list) or not local_files:
            raise ValueError(f'来源缺少 local_files：{source.get("source_title", "")}')
        derived_files = source.get('derived_files') or []
        if not isinstance(derived_files, list):
            raise ValueError('derived_files 必须是数组')
        inspected_files = []
        extraction_rules = []
        for raw_file_name in local_files + derived_files:
            file_name = normalize_text(raw_file_name)
            try:
                source_path = resolve_source_path(source_dir, file_name)
                inspection, suggested_rules = inspect_source_file(
                    source_path, file_name
                )
                extraction_rules.extend(suggested_rules)
            except Exception as exc:
                error_count += 1
                inspection = {
                    'file': file_name,
                    'inspection_status': 'error',
                    'error': normalize_text(exc),
                }
            status_counts[inspection['inspection_status']] += 1
            inspected_files.append(inspection)
        source_plans.append({
            'source_title': normalize_text(source.get('source_title')),
            'publisher': normalize_text(source.get('publisher')),
            'publication_date': normalize_text(source.get('publication_date')),
            'landing_page_url': normalize_text(source.get('landing_page_url')),
            'content_url': normalize_text(source.get('content_url')),
            'covered_school_types': source.get('covered_school_types') or [],
            'contains_address': bool(source.get('contains_address')),
            'files': inspected_files,
            'extraction_rules': extraction_rules,
            'review_status': 'pending',
        })
    extraction_plan = {
        'stage': 'basic_education_extraction_plan',
        'city_context': city_context,
        'administrative_unit': administrative_unit,
        'government_source_file': Path(
            os.path.relpath(input_path, output_path.parent.resolve())
        ).as_posix(),
        'items': source_plans,
        'inspection_summary': {
            'source_count': len(source_plans),
            'file_count': sum(
                len(source_plan['files']) for source_plan in source_plans
            ),
            'suggested_rule_count': sum(
                len(source_plan['extraction_rules'])
                for source_plan in source_plans
            ),
            'status_counts': dict(sorted(status_counts.items())),
            'error_count': error_count,
        },
    }
    return extraction_plan, 1 if error_count else 0
