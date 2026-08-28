"""检查来源资料并构造基础教育学校地址记录。"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_readers import (  # noqa: E402
    detect_source_format,
    load_source_html,
    load_source_tables,
    normalize_text,
)


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
EXPLICIT_CAMPUS_LABEL = (
    r'(?:校本部|初中部|小学部|高中部|总校|分校|总园|'
    r'校本部(?:初中部|小学部|高中部)|'
    r'[^\s：:（）()号]{1,20}(?:校区|园区|教学点))'
)
CAMPUS_PREFIX_PATTERN = re.compile(
    rf'(?P<campus>{EXPLICIT_CAMPUS_LABEL})[：:]\s*'
)
CAMPUS_SUFFIX_PATTERN = re.compile(
    rf'^(?P<address>.+?)[（(](?P<campus>{EXPLICIT_CAMPUS_LABEL})[）)]$'
)
CAMPUS_SUFFIX_SEGMENT_PATTERN = re.compile(
    rf'(?P<address>.+?)[（(](?P<campus>{EXPLICIT_CAMPUS_LABEL})[）)]'
)
CAMPUS_PAREN_PREFIX_PATTERN = re.compile(
    rf'[（(](?P<campus>{EXPLICIT_CAMPUS_LABEL})[）)]\s*'
)
GRADE_NOTE_PATTERN = re.compile(
    r'[（(](?:初|高|小|一|二|三|四|五|六|七|八|九|年级|至|、|，|,|\s)+[）)]$'
)
NON_RECORD_NAME_PATTERN = re.compile(
    r'^(?:更新时间|更新日期|数据截止|截至日期|填表|制表|备注|说明|合计|总计)'
)
CHINESE_NAME_SPACE_PATTERN = re.compile(
    r'(?<=[\u3400-\u9fff（）])\s+(?=[\u3400-\u9fff（）])'
)


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


def normalize_school_type_part(school_type_part: str) -> str:
    """规范单个学校类型或学段名称。"""
    school_type_part = normalize_text(school_type_part)
    year_match = re.search(
        r'([零〇一二三四五六七八九十百\d]+)年(?:一贯)?制(?:学校)?',
        school_type_part,
    )
    if year_match:
        return f'{year_match.group(1)}年一贯制学校'
    mappings = (
        (r'职业高级中学|职业高中', '职业高级中学'),
        (r'中等职业|中职|中等专业', '中等职业学校'),
        (r'特殊教育|培智', '特殊教育学校'),
        (r'技师学院|技工学校', '技工院校'),
        (r'专门学校', '专门学校'),
        (r'成人中等', '成人中等学校'),
        (r'完全中学|完中', '完全中学'),
        (r'幼儿园', '幼儿园'),
        (r'小学', '小学'),
        (r'初级中学|初中', '初中'),
        (r'高级中学|普通高中|高中', '高中'),
    )
    return next(
        (
            normalized
            for pattern, normalized in mappings
            if re.search(pattern, school_type_part)
        ),
        school_type_part,
    )


def normalize_school_type(school_type_text: Any) -> str:
    """规范官方学校类型并保留无法识别的原文。"""
    normalized_text = re.sub(
        r'[（(].*?[）)]', '', normalize_text(school_type_text)
    )
    school_type_parts = [
        school_type_part
        for school_type_part in re.split(r'[、，,;/；]+', normalized_text)
        if normalize_text(school_type_part)
    ]
    return '、'.join(
        normalize_school_type_part(school_type_part)
        for school_type_part in school_type_parts
    )


def normalize_school_nature(school_nature_text: Any) -> str:
    """把明确办学性质规范为公办或民办，其余保留原文。"""
    normalized_nature = normalize_text(school_nature_text)
    if '公办' in normalized_nature:
        return '公办'
    if '民办' in normalized_nature:
        return '民办'
    return normalized_nature


def resolve_publication_date(publication_date: Any) -> str:
    """优先使用来源发布日期，缺失时返回当天日期。"""
    return normalize_text(publication_date) or date.today().isoformat()


def normalize_place_name_text(place_name: Any) -> str:
    """移除学校中文名称内部由断行或提取产生的空格。"""
    return CHINESE_NAME_SPACE_PATTERN.sub('', normalize_text(place_name))


def read_table_cell(table_row: list[str], column_index: int | None) -> str:
    """按一基列号安全读取单元格。"""
    if column_index is None:
        return ''
    if not isinstance(column_index, int) or column_index < 1:
        raise ValueError('列号必须是从 1 开始的整数')
    return table_row[column_index - 1] if column_index <= len(table_row) else ''


def classify_school_type_from_presence(
    table_row: list[str], column_mappings: list[dict[str, Any]]
) -> str:
    """根据非零招生人数列组合学校类型。"""
    school_types = []
    for column_mapping in column_mappings:
        cell_value = read_table_cell(table_row, column_mapping['column'])
        if cell_value not in {'', '0', '0.0', '/', '-', '—'}:
            school_types.append(column_mapping['value'])
    return '、'.join(dict.fromkeys(school_types))


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
    sources = source_manifest.get('sources')
    if not isinstance(sources, list):
        raise ValueError('来源清单必须包含 sources 数组')
    source_dir = input_path.parent.resolve()
    source_plans = []
    status_counts: Counter[str] = Counter()
    error_count = 0
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('sources 中的每项必须是对象')
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
        'schema_version': '1.0',
        'stage': 'basic_education_extraction_plan',
        'city': normalize_text(source_manifest.get('city')),
        'administrative_unit': source_manifest.get('administrative_unit') or {},
        'source_manifest': Path(
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


def format_source_reference(
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


def append_campus_name(place_name: str, campus_name: str) -> str:
    """把明确校区名称拼接到学校名称。"""
    place_name = normalize_text(place_name)
    campus_name = normalize_text(campus_name)
    return place_name if campus_name in place_name else place_name + campus_name


def split_explicit_campus_addresses(
    place_name: str, original_address: str
) -> list[tuple[str, str]]:
    """拆分带明确校区标签的单行或多行地址。"""
    raw_lines = [
        normalize_text(address_line)
        for address_line in str(original_address).splitlines()
        if normalize_text(address_line)
    ]
    lines = []
    for line in raw_lines:
        parts = [
            normalize_text(address_part)
            for address_part in re.split(r'[/／]', line)
        ]
        if len(parts) > 1 and all(CAMPUS_SUFFIX_PATTERN.fullmatch(part) for part in parts):
            lines.extend(parts)
        else:
            lines.append(line)
    locations = []
    for line in lines:
        matches = list(CAMPUS_PREFIX_PATTERN.finditer(line))
        if matches and matches[0].start() == 0:
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                address = GRADE_NOTE_PATTERN.sub('', line[match.end():end]).strip()
                if not address:
                    return [(place_name, original_address)]
                locations.append((
                    append_campus_name(place_name, match.group('campus')),
                    address,
                ))
            continue
        matches = list(CAMPUS_PAREN_PREFIX_PATTERN.finditer(line))
        if matches and matches[0].start() == 0:
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                address = normalize_text(
                    line[match.end():end].strip('；;，, ')
                )
                if not address:
                    return [(place_name, original_address)]
                locations.append((
                    append_campus_name(place_name, match.group('campus')),
                    address,
                ))
            continue
        suffix_segments = list(CAMPUS_SUFFIX_SEGMENT_PATTERN.finditer(line))
        if (
            len(suffix_segments) > 1
            and ''.join(match.group(0) for match in suffix_segments) == line
        ):
            locations.extend((
                append_campus_name(place_name, match.group('campus')),
                match.group('address'),
            ) for match in suffix_segments)
            continue
        suffix_match = CAMPUS_SUFFIX_PATTERN.fullmatch(line)
        if suffix_match is None:
            return [(place_name, original_address)]
        locations.append((
            append_campus_name(place_name, suffix_match.group('campus')),
            suffix_match.group('address'),
        ))
    return locations or [(place_name, original_address)]


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
    return {
        'place_name': normalize_place_name_text(place_name),
        'original_address': normalize_text(original_address),
        'source_nature': 'government_information',
        'source_reference': format_source_reference(
            source_record, source_location
        ),
        'attributes': {
            'administrative_unit': administrative_unit,
            'school_type': normalize_school_type(school_type),
            'school_nature': normalize_school_nature(school_nature),
            'publication_date': resolve_publication_date(
                source_record.get('publication_date')
            ),
        },
    }


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
        campus_locations = split_explicit_campus_addresses(
            place_name, read_table_cell(table_row, address_column)
        )
        for location_index, (location_name, location_address) in enumerate(
            campus_locations, start=1
        ):
            record_location = location_text
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
        records.append(build_school_record(
            place_name,
            normalize_text(address_element.get_text(' ', strip=True))
            if address_element else '',
            normalize_text(school_type_element.get_text(' ', strip=True))
            if school_type_element else school_type_value,
            school_nature_value or (
                normalize_text(
                    school_nature_element.get_text(' ', strip=True)
                )
                if school_nature_element else ''
            ),
            source_record,
            source_location,
            administrative_unit,
        ))
    return records


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


def deduplicate_school_records(
    school_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """按学校名称和原始地址合并记录并补全学校类型。"""
    unique_records = []
    records_by_key = {}
    for school_record in school_records:
        record_key = (
            school_record['place_name'], school_record['original_address']
        )
        if record_key not in records_by_key:
            records_by_key[record_key] = school_record
            unique_records.append(school_record)
            continue
        current_type = records_by_key[record_key]['attributes']['school_type']
        incoming_type = school_record['attributes']['school_type']
        school_types = [
            school_type
            for school_type in (current_type + '、' + incoming_type).split('、')
            if school_type
        ]
        records_by_key[record_key]['attributes']['school_type'] = '、'.join(
            dict.fromkeys(school_types)
        )
    return unique_records, len(school_records) - len(unique_records)


def extract_school_records(plan_path: Path) -> tuple[dict[str, Any], int]:
    """执行已复核计划并生成公共地址输入。"""
    extraction_plan = read_json_object(plan_path)
    if extraction_plan.get('stage') != 'basic_education_extraction_plan':
        raise ValueError('输入必须是 basic_education_extraction_plan JSON')
    source_manifest_path = (
        plan_path.parent
        / normalize_text(extraction_plan.get('source_manifest'))
    ).resolve()
    source_dir = source_manifest_path.parent
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
                source_path = resolve_source_path(
                    source_dir, normalize_text(extraction_rule.get('file'))
                )
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
                                table_candidate, extraction_rule
                            )
                        ),
                        None,
                    )
                    if source_table is None:
                        raise ValueError('找不到规则指定的表格')
                    extracted_records = extract_table_records(
                        source_table,
                        extraction_rule,
                        source_plan,
                        administrative_unit,
                    )
                elif extraction_rule.get('kind') == 'html_css':
                    extracted_records = extract_html_css_records(
                        source_path,
                        extraction_rule,
                        source_plan,
                        administrative_unit,
                    )
                elif extraction_rule.get('kind') == 'text_regex':
                    extracted_records = extract_text_records(
                        source_path,
                        extraction_rule,
                        source_plan,
                        administrative_unit,
                    )
                else:
                    raise ValueError(
                        f'不支持的规则类型：{extraction_rule.get("kind")}'
                    )
                if not extracted_records:
                    raise ValueError('规则没有提取到任何学校')
                records.extend(extracted_records)
            except Exception as exc:
                error_messages.append(
                    f'{source_title} 规则 {rule_index}：{normalize_text(exc)}'
                )
    records, duplicate_count = deduplicate_school_records(records)
    address_payload = {
        'schema_version': '1.0',
        'stage': (
            'address_records'
            if not error_messages
            else 'address_records_incomplete'
        ),
        'city': normalize_text(extraction_plan.get('city')),
        'items': records,
        'metrics': {
            'source_count': len(source_plans),
            'reviewed_source_count': reviewed_count,
            'skipped_source_count': skipped_count,
            'approved_rule_count': approved_count,
            'item_count': len(records),
            'missing_address_count': sum(
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


def build_argument_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description='检查并提取基础教育学校地址')
    commands = parser.add_subparsers(dest='command', required=True)
    inspect_command = commands.add_parser('inspect', help='生成提取计划')
    inspect_command.add_argument('--input', required=True, help='sources.json 路径')
    inspect_command.add_argument('--output', required=True, help='计划输出路径')
    extract_command = commands.add_parser('extract', help='执行已复核计划')
    extract_command.add_argument('--plan', required=True, help='提取计划路径')
    extract_command.add_argument('--output', required=True, help='地址记录输出路径')
    return parser


def main() -> int:
    """执行来源检查或学校地址提取。"""
    arguments = build_argument_parser().parse_args()
    try:
        output_path = Path(arguments.output).resolve()
        if arguments.command == 'inspect':
            output_payload, exit_code = build_extraction_plan(
                Path(arguments.input).resolve(), output_path
            )
        else:
            output_payload, exit_code = extract_school_records(
                Path(arguments.plan).resolve()
            )
        write_json_object(output_path, output_payload)
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
