"""执行已复核规则并构造基础教育学校地址记录。"""

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from source_readers import (
    detect_source_format,
    load_source_html,
    load_source_tables,
    normalize_text,
)
from query_city_core.city import validate_city_context
from query_city_core.io_utils import read_json_payload
from inspect_government_source import (
    ADDRESS_HEADERS,
    EXACT_PLACE_HEADERS,
    PLACE_HEADERS,
    SCHOOL_NATURE_HEADERS,
    SCHOOL_TYPE_HEADERS,
    is_place_name_header,
    read_table_cell,
    resolve_source_path,
)
from normalize_school_records import (
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


def validate_positive_index(index_value: Any, field_name: str) -> int:
    """校验规则中的一基索引。"""
    if not isinstance(index_value, int) or index_value < 1:
        raise ValueError(f'{field_name} 必须是从 1 开始的整数')
    return index_value


def is_table_location_match(
    source_table: dict[str, Any], extraction_rule: dict[str, Any]
) -> bool:
    """判断二维表是否对应提取规则。"""
    return source_table['kind'] == extraction_rule.get('kind') and source_table[
        'location'
    ] == (
        extraction_rule.get('location') or {}
    )


def build_source_reference(
    source_record: dict[str, Any], source_location: str
) -> str:
    """组合来源链接和文件内定位。"""
    source_url = normalize_text(
        source_record.get('content_url')
        or source_record.get('landing_page_url')
    )
    return (
        f'{source_url} | {source_location}' if source_url else source_location
    )


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
        'source_reference': build_source_reference(
            source_record, source_location
        ),
        'attributes': {
            'administrative_unit': administrative_unit,
            'school_type': normalized_school_type,
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


def extract_table_records(
    source_table: dict[str, Any],
    extraction_rule: dict[str, Any],
    source_record: dict[str, Any],
    administrative_unit: str,
) -> list[dict[str, Any]]:
    """按列映射提取二维表中的学校和地址。"""
    table_rows = source_table['rows']
    start_row = validate_positive_index(
        extraction_rule.get('data_start_row'), 'data_start_row'
    )
    end_row_value = extraction_rule.get('data_end_row')
    end_row = (
        len(table_rows)
        if end_row_value is None
        else validate_positive_index(end_row_value, 'data_end_row')
    )
    place_columns = extraction_rule.get('place_name_columns')
    if not isinstance(place_columns, list) or not place_columns:
        raise ValueError('place_name_columns 必须是非空数组')
    place_columns = [
        validate_positive_index(column_index, 'place_name_columns')
        for column_index in place_columns
    ]
    address_column = extraction_rule.get('original_address_column')
    if address_column is not None:
        address_column = validate_positive_index(
            address_column, 'original_address_column'
        )
    school_type_column = extraction_rule.get('school_type_column')
    if school_type_column is not None:
        school_type_column = validate_positive_index(
            school_type_column, 'school_type_column'
        )
    school_type_value = normalize_text(extraction_rule.get('school_type_value'))
    presence_mappings = (
        extraction_rule.get('school_type_presence_columns') or []
    )
    if not isinstance(presence_mappings, list):
        raise ValueError('school_type_presence_columns 必须是数组')
    presence_mappings = [
        {
            'column': validate_positive_index(
                presence_mapping.get('column'), 'column'
            ),
            'value': normalize_text(presence_mapping.get('value')),
        }
        for presence_mapping in presence_mappings
        if isinstance(presence_mapping, dict)
        and normalize_text(presence_mapping.get('value'))
    ]
    school_nature_column = extraction_rule.get('school_nature_column')
    if school_nature_column is not None:
        school_nature_column = validate_positive_index(
            school_nature_column, 'school_nature_column'
        )
    school_nature_value = normalize_text(
        extraction_rule.get('school_nature_value')
    )
    fill_columns = {
        validate_positive_index(column_index, 'fill_down_columns')
        for column_index in (extraction_rule.get('fill_down_columns') or [])
    }
    required_values = extraction_rule.get('required_cell_values') or []
    if not isinstance(required_values, list):
        raise ValueError('required_cell_values 必须是数组')
    required_values = [
        {
            'column': validate_positive_index(
                required_mapping.get('column'), 'column'
            ),
            'value': normalize_text(required_mapping.get('value')),
        }
        for required_mapping in required_values
        if isinstance(required_mapping, dict)
    ]
    excluded_rows = {
        validate_positive_index(row_index, 'exclude_rows')
        for row_index in (extraction_rule.get('exclude_rows') or [])
    }
    filled_values: dict[int, str] = {}
    records = []
    for row_number in range(start_row, min(end_row, len(table_rows)) + 1):
        if row_number in excluded_rows:
            continue
        table_row = list(table_rows[row_number - 1])
        if any(
            read_table_cell(table_row, required_mapping['column'])
            != required_mapping['value']
            for required_mapping in required_values
        ):
            continue
        for column_index in fill_columns:
            cell_value = read_table_cell(table_row, column_index)
            if cell_value:
                filled_values[column_index] = cell_value
            elif column_index in filled_values:
                while len(table_row) < column_index:
                    table_row.append('')
                table_row[column_index - 1] = filled_values[column_index]
        name_parts = [
            read_table_cell(table_row, column_index)
            for column_index in place_columns
        ]
        place_name = str(
            extraction_rule.get('place_name_separator') or ''
        ).join(
            name_part for name_part in name_parts if name_part
        )
        if (
            not place_name
            or is_non_school_record_name(place_name)
            or any(is_place_name_header(name_part) for name_part in name_parts)
        ):
            continue
        location_text = ' | '.join(
            [extraction_rule['file']]
            + [
                f'{location_key} {location_value}'
                for location_key, location_value in source_table['location'].items()
            ]
            + [f'row {row_number}']
        )
        school_type = (
            classify_school_type_from_presence(table_row, presence_mappings)
            or read_table_cell(table_row, school_type_column)
            or school_type_value
        )
        school_nature = school_nature_value or read_table_cell(
            table_row, school_nature_column
        )
        records.extend(build_records_for_locations(
            place_name,
            read_table_cell(table_row, address_column),
            school_type,
            school_nature,
            source_record,
            location_text,
            administrative_unit,
        ))
    return records


def extract_html_css_records(
    source_path: Path,
    extraction_rule: dict[str, Any],
    source_record: dict[str, Any],
    administrative_unit: str,
) -> list[dict[str, Any]]:
    """按 CSS 选择器提取重复网页记录。"""
    from bs4 import BeautifulSoup

    row_selector = normalize_text(extraction_rule.get('row_selector'))
    name_selector = normalize_text(extraction_rule.get('place_name_selector'))
    address_selector = normalize_text(
        extraction_rule.get('original_address_selector')
    )
    school_type_selector = normalize_text(
        extraction_rule.get('school_type_selector')
    )
    school_type_value = normalize_text(
        extraction_rule.get('school_type_value')
    )
    school_nature_selector = normalize_text(
        extraction_rule.get('school_nature_selector')
    )
    school_nature_value = normalize_text(
        extraction_rule.get('school_nature_value')
    )
    if not row_selector or not name_selector:
        raise ValueError('html_css 规则缺少行或学校选择器')
    excluded_rows = set(extraction_rule.get('exclude_rows') or [])
    soup = BeautifulSoup(load_source_html(source_path), 'lxml')
    records = []
    for row_number, element in enumerate(soup.select(row_selector), start=1):
        if row_number in excluded_rows:
            continue
        name_element = element.select_one(name_selector)
        address_element = element.select_one(address_selector) if address_selector else None
        school_type_element = (
            element.select_one(school_type_selector) if school_type_selector else None
        )
        school_nature_element = (
            element.select_one(school_nature_selector)
            if school_nature_selector else None
        )
        place_name = normalize_text(
            name_element.get_text(' ', strip=True) if name_element else ''
        )
        if not place_name or is_non_school_record_name(place_name):
            continue
        source_location = (
            f'{source_path.name} | {row_selector} | row {row_number}'
        )
        address_text = (
            normalize_text(address_element.get_text(' ', strip=True))
            if address_element else ''
        )
        school_type = (
            normalize_text(school_type_element.get_text(' ', strip=True))
            if school_type_element else school_type_value
        )
        school_nature = school_nature_value or (
            normalize_text(school_nature_element.get_text(' ', strip=True))
            if school_nature_element else ''
        )
        records.extend(build_records_for_locations(
            place_name,
            address_text,
            school_type,
            school_nature,
            source_record,
            source_location,
            administrative_unit,
        ))
    return records


def normalize_key_value_label(label_text: Any) -> str:
    """统一详情页纵向字段名称。"""
    return re.sub(r'[\s（）()：:、/\\_\-]+', '', normalize_text(label_text))


def read_key_value_field(
    fields: dict[str, str], configured_labels: Any, default_labels: tuple[str, ...]
) -> str:
    """按已复核标签或默认官方表头读取详情页字段。"""
    labels = configured_labels or default_labels
    if not isinstance(labels, (list, tuple)):
        raise ValueError('html_key_value 字段标签必须是数组')
    for label in labels:
        field_value = fields.get(normalize_key_value_label(label))
        if field_value:
            return field_value
    return ''


def extract_html_key_value_records(
    source_path: Path,
    extraction_rule: dict[str, Any],
    source_record: dict[str, Any],
    administrative_unit: str,
) -> list[dict[str, Any]]:
    """从政府学校详情页的纵向键值表提取一条或多校区记录。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(load_source_html(source_path), 'lxml')
    fields = {}
    for table_row in soup.select('table tr'):
        cells = table_row.find_all(['th', 'td'], recursive=False)
        if len(cells) < 2:
            continue
        field_label = normalize_key_value_label(
            cells[0].get_text(' ', strip=True)
        )
        field_value = normalize_text(cells[1].get_text(' ', strip=True))
        if field_label and field_value:
            fields.setdefault(field_label, field_value)
    place_name = read_key_value_field(
        fields,
        extraction_rule.get('place_name_labels'),
        PLACE_HEADERS + EXACT_PLACE_HEADERS,
    )
    if not place_name or is_non_school_record_name(place_name):
        return []
    original_address = read_key_value_field(
        fields,
        extraction_rule.get('original_address_labels'),
        ADDRESS_HEADERS,
    )
    school_type = read_key_value_field(
        fields,
        extraction_rule.get('school_type_labels'),
        SCHOOL_TYPE_HEADERS,
    ) or normalize_text(extraction_rule.get('school_type_value'))
    school_nature = read_key_value_field(
        fields,
        extraction_rule.get('school_nature_labels'),
        SCHOOL_NATURE_HEADERS,
    ) or normalize_text(extraction_rule.get('school_nature_value'))
    return build_records_for_locations(
        place_name,
        original_address,
        school_type,
        school_nature,
        source_record,
        f'{source_path.name} | key-value table',
        administrative_unit,
    )


def extract_text_segments(
    source_path: Path, source_location: dict[str, Any]
) -> list[tuple[str, str]]:
    """读取可供正则提取的网页、Word 或 PDF 文本。"""
    file_format = detect_source_format(source_path)
    if file_format in {'html', 'word'}:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(load_source_html(source_path), 'lxml')
        return [(soup.get_text('\n', strip=True), source_path.name)]
    if file_format == 'pdf':
        import pymupdf

        with pymupdf.open(source_path) as document:
            start_page = int(source_location.get('page_start') or 1)
            end_page = int(source_location.get('page_end') or len(document))
            return [
                (
                    document[index - 1].get_text('text', sort=True),
                    f'{source_path.name} | page {index}',
                )
                for index in range(
                    max(start_page, 1), min(end_page, len(document)) + 1
                )
            ]
    raise ValueError('text_regex 只支持 HTML、Word 和 PDF')


def extract_text_records(
    source_path: Path,
    extraction_rule: dict[str, Any],
    source_record: dict[str, Any],
    administrative_unit: str,
) -> list[dict[str, Any]]:
    """按命名正则提取正文中的学校和地址。"""
    pattern = re.compile(
        str(extraction_rule.get('pattern') or ''), re.MULTILINE
    )
    if 'place_name' not in pattern.groupindex:
        raise ValueError('text_regex 必须包含 place_name 命名组')
    records = []
    for segment_text, source_location in extract_text_segments(
        source_path, extraction_rule.get('location') or {}
    ):
        for match in pattern.finditer(segment_text):
            matched_fields = match.groupdict()
            place_name = normalize_text(matched_fields.get('place_name'))
            if not place_name or is_non_school_record_name(place_name):
                continue
            records.append(build_school_record(
                place_name,
                normalize_text(matched_fields.get('original_address')),
                normalize_text(matched_fields.get('school_type'))
                or normalize_text(extraction_rule.get('school_type_value')),
                normalize_text(extraction_rule.get('school_nature_value'))
                or normalize_text(matched_fields.get('school_nature')),
                source_record,
                source_location,
                administrative_unit,
            ))
    return records


def resolve_rule_source_files(
    source_dir: Path,
    source_plan: dict[str, Any],
    extraction_rule: dict[str, Any],
) -> list[tuple[Path, str, str]]:
    """把单文件或文件模式规则限定到来源清单已经登记的文件。"""
    declared_files = {
        normalize_text(source_file.get('file')): source_file
        for source_file in (source_plan.get('files') or [])
        if isinstance(source_file, dict)
        and normalize_text(source_file.get('file'))
    }
    file_name = normalize_text(extraction_rule.get('file'))
    file_pattern = normalize_text(extraction_rule.get('file_pattern'))
    if bool(file_name) == bool(file_pattern):
        raise ValueError('提取规则必须且只能包含 file 或 file_pattern')
    matched_names = (
        [file_name]
        if file_name
        else [
            declared_name for declared_name in declared_files
            if fnmatch(declared_name.replace('\\', '/'), file_pattern)
        ]
    )
    if not matched_names:
        raise ValueError(f'file_pattern 没有匹配已登记文件：{file_pattern}')
    resolved_files = []
    for matched_name in matched_names:
        if matched_name not in declared_files:
            raise ValueError(f'提取规则引用未登记文件：{matched_name}')
        resolved_files.append((
            resolve_source_path(source_dir, matched_name),
            matched_name,
            normalize_text(declared_files[matched_name].get('source_url')),
        ))
    return resolved_files


def extract_school_records(plan_path: Path) -> tuple[dict[str, Any], int]:
    """执行已复核计划并生成公共地址输入。"""
    extraction_plan = read_json_payload(plan_path)
    if extraction_plan.get('stage') != 'basic_education_extraction_plan':
        raise ValueError('输入必须是 basic_education_extraction_plan JSON')
    government_source_path = (
        plan_path.parent
        / normalize_text(extraction_plan.get('government_source_file'))
    ).resolve()
    source_dir = government_source_path.parent
    administrative_unit = normalize_text(
        (extraction_plan.get('administrative_unit') or {}).get('name')
    )
    source_plans = extraction_plan.get('items')
    if not isinstance(source_plans, list):
        raise ValueError('提取计划必须包含 items 数组')
    table_cache: dict[Path, list[dict[str, Any]]] = {}
    records = []
    error_messages = []
    reviewed_count = 0
    skipped_count = 0
    approved_count = 0
    for source_index, source_plan in enumerate(source_plans, start=1):
        source_title = (
            normalize_text(source_plan.get('source_title'))
            or f'来源 {source_index}'
        )
        if source_plan.get('review_status') == 'skipped':
            source_files = source_plan.get('files') or []
            if (
                source_plan.get('skip_reason') != 'no_vision_capability'
                or not source_files
                or any(
                    source_file.get('inspection_status') != 'needs_vision'
                    for source_file in source_files
                )
            ):
                error_messages.append(f'{source_title} 的跳过标记无效')
            else:
                skipped_count += 1
            continue
        if source_plan.get('review_status') != 'ready':
            error_messages.append(f'{source_title} 尚未完成提取计划复核')
            continue
        reviewed_count += 1
        extraction_rules = [
            rule for rule in (source_plan.get('extraction_rules') or [])
            if isinstance(rule, dict) and rule.get('approved') is True
        ]
        if not extraction_rules:
            error_messages.append(f'{source_title} 没有已批准的提取规则')
            continue
        for rule_index, extraction_rule in enumerate(extraction_rules, start=1):
            approved_count += 1
            try:
                rule_sources = resolve_rule_source_files(
                    source_dir, source_plan, extraction_rule
                )
                for source_path, source_file_name, source_url in rule_sources:
                    effective_rule = dict(extraction_rule)
                    effective_rule['file'] = source_file_name
                    effective_rule.pop('file_pattern', None)
                    effective_source_plan = dict(source_plan)
                    if source_url:
                        effective_source_plan['content_url'] = source_url
                    if extraction_rule.get('kind') in {
                        'table', 'sheet', 'pdf_table', 'vision_table'
                    }:
                        if source_path not in table_cache:
                            table_cache[source_path] = load_source_tables(
                                source_path
                            )[0]
                        source_table = next(
                            (
                                table_candidate
                                for table_candidate in table_cache[source_path]
                                if is_table_location_match(
                                    table_candidate, effective_rule
                                )
                            ),
                            None,
                        )
                        if source_table is None:
                            raise ValueError('找不到规则指定的表格')
                        extracted_records = extract_table_records(
                            source_table,
                            effective_rule,
                            effective_source_plan,
                            administrative_unit,
                        )
                    elif extraction_rule.get('kind') == 'html_css':
                        extracted_records = extract_html_css_records(
                            source_path,
                            effective_rule,
                            effective_source_plan,
                            administrative_unit,
                        )
                    elif extraction_rule.get('kind') == 'html_key_value':
                        extracted_records = extract_html_key_value_records(
                            source_path,
                            effective_rule,
                            effective_source_plan,
                            administrative_unit,
                        )
                    elif extraction_rule.get('kind') == 'text_regex':
                        extracted_records = extract_text_records(
                            source_path,
                            effective_rule,
                            effective_source_plan,
                            administrative_unit,
                        )
                    else:
                        raise ValueError(
                            '不支持的规则类型：'
                            f'{extraction_rule.get("kind")}'
                        )
                    if not extracted_records:
                        raise ValueError(
                            f'规则没有从 {source_file_name} 提取到任何学校'
                        )
                    records.extend(extracted_records)
            except Exception as exc:
                error_messages.append(
                    f'{source_title} 规则 {rule_index}：{normalize_text(exc)}'
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
            'source_count': len(source_plans),
            'reviewed_source_count': reviewed_count,
            'skipped_source_count': skipped_count,
            'approved_rule_count': approved_count,
            'item_count': len(records),
            'original_address_count': sum(
                bool(record['original_address']) for record in records
            ),
            'missing_original_address_count': sum(
                not record['original_address'] for record in records
            ),
            'missing_school_type_count': sum(
                not record['attributes']['school_type'] for record in records
            ),
            'missing_school_nature_count': sum(
                not record['attributes']['school_nature'] for record in records
            ),
            'duplicate_count': duplicate_count,
            'error_count': len(error_messages),
        },
        'errors': error_messages,
    }
    return address_payload, 1 if error_messages else 0
