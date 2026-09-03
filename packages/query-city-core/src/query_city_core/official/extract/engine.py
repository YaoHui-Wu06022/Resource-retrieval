"""通用政府来源检查与提取引擎。

本模块把“来源清单检查 → 提取计划 → 按已批准规则提取记录”的公共流程收进
核心层。场景层通过 ``FieldTerms`` 注入表头/标签词表，通过回调完成清单校验、
自定义来源检查、默认值注入和记录构造；核心不感知学校、医疗机构等语义。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable

from ...io_utils import read_json_payload
from ..readers import load_source_html, load_source_tables, normalize_text
from .extract_utils import (
    build_source_reference,
    extract_text_segments,
    is_table_location_match,
    normalize_key_value_label,
    read_key_value_field,
    validate_positive_index,
)
from .rules import (
    FieldTerms,
    consolidate_html_key_value_rules,
    inspect_source_file as _inspect_source_file,
    read_table_cell,
    resolve_source_path,
)


TABLE_RULE_KINDS = {'table', 'sheet', 'pdf_table', 'vision_table'}
OBJECT_LIST_RULE_KINDS = {'object_list'}
JSONP_PATTERN = re.compile(r'^\s*[\w.]+\s*\((.*)\)\s*;?\s*$', re.DOTALL)
JS_ASSIGNMENT_FIELD_PATTERN = re.compile(r'^\w+$')


def _source_location_parts(file_name, location):
    """把文件内定位格式化为展示文本。"""
    parts = [normalize_text(file_name)]
    for location_key, location_value in (location or {}).items():
        parts.append(f'{location_key} {location_value}')
    return parts


def _attribute_entries(extraction_rule):
    """按 field 索引规则中的中性 attribute_fields。"""
    entries = {}
    for entry in extraction_rule.get('attribute_fields') or []:
        if not isinstance(entry, dict) or not entry.get('field'):
            continue
        entries[entry['field']] = entry
    return entries


def _entry_table_value(entry, table_row):
    """从表格行读取属性单元格值或固定值。"""
    column = entry.get('column')
    if column is not None:
        return normalize_text(read_table_cell(
            table_row,
            validate_positive_index(column, 'attribute_fields.column'),
        ))
    return normalize_text(entry.get('value'))


def _entry_element_value(entry, element):
    """从 HTML 元素读取属性文本或固定值。"""
    selector = normalize_text(entry.get('selector'))
    if selector:
        child = element.select_one(selector) if element is not None else None
        if child is not None:
            return normalize_text(child.get_text(' ', strip=True))
        return ''
    return normalize_text(entry.get('value'))


def _entry_object_value(entry, item):
    """从 JSON/内嵌对象读取属性键值或固定值。"""
    keys = entry.get('keys')
    if isinstance(keys, (list, tuple)):
        for key in keys:
            value = item.get(str(key))
            if value is not None and normalize_text(value):
                return normalize_text(value)
        return ''
    return normalize_text(entry.get('value'))


def _entry_text_match_value(entry, matched_fields):
    """从正则命名组或固定值读取属性。"""
    field = str(entry.get('field') or '')
    group_value = matched_fields.get(field)
    if group_value:
        return normalize_text(group_value)
    return normalize_text(entry.get('value'))


def _effective_source_plan(source_plan, source_url):
    """构造带具体来源网址的规则执行上下文。"""
    effective_plan = dict(source_plan)
    if source_url:
        effective_plan['content_url'] = source_url
    return effective_plan


def _build_raw_record(
    *,
    place_name,
    original_address,
    attributes,
    rule,
    source_reference,
    source_item,
    row=None,
):
    """构造一条中性原始提取记录。"""
    return {
        'place_name': normalize_text(place_name),
        'original_address': normalize_text(original_address),
        'attributes': dict(attributes),
        'row': row,
        'rule': dict(rule),
        'source_reference': source_reference,
        'source_item': source_item,
    }


def inspect_government_source(
    source_manifest_path: Path,
    output_path: Path,
    terms: FieldTerms,
    *,
    plan_stage: str,
    validate_manifest: Callable[
        [dict], tuple[dict, dict | None, list[dict]]
    ],
    inspect_source_file: (
        Callable[[Path, str], tuple[dict, list[dict]]] | None
    ) = None,
    decorate_source_plan: (
        Callable[[dict, list[dict], list[dict]], None] | None
    ) = None,
) -> tuple[dict, int]:
    """检查政府来源清单并生成待复核的提取计划。

    ``validate_manifest`` 由场景层校验并返回
    ``(city_context, administrative_unit, source_items)``。约定每个
    source_item 已包含引擎需要的 ``local_files``（非空字符串列表）与
    ``derived_files``（可为空列表），同时保留场景自有字段。
    """
    source_manifest = read_json_payload(source_manifest_path)
    city_context, administrative_unit, source_items = validate_manifest(
        source_manifest
    )
    source_dir = Path(source_manifest_path).resolve().parent
    inspect_source = inspect_source_file or (
        lambda path, file_name: _inspect_source_file(
            path, file_name, terms
        )
    )
    source_plans = []
    status_counts: Counter[str] = Counter()
    error_count = 0
    for source_index, source_item in enumerate(source_items, start=1):
        if not isinstance(source_item, dict):
            raise ValueError(f'来源 {source_index} 必须是对象')
        local_files = source_item.get('local_files')
        if not isinstance(local_files, list) or not local_files:
            raise ValueError(
                f'来源 {source_index} 缺少 local_files 非空列表'
            )
        derived_files = source_item.get('derived_files') or []
        if not isinstance(derived_files, list):
            raise ValueError(f'来源 {source_index} 的 derived_files 必须是数组')
        inspected_files = []
        extraction_rules = []
        local_file_urls = source_item.get('local_file_urls') or {}
        for raw_file_name in list(local_files) + list(derived_files):
            file_name = normalize_text(raw_file_name)
            try:
                source_path = resolve_source_path(source_dir, file_name)
                inspection, suggested_rules = inspect_source(
                    source_path, file_name
                )
                if file_name in local_file_urls:
                    inspection['source_url'] = normalize_text(
                        local_file_urls[file_name]
                    )
                extraction_rules.extend(suggested_rules)
            except Exception as exc:  # noqa: BLE001 - 单文件失败不中断整批
                error_count += 1
                inspection = {
                    'file': file_name,
                    'inspection_status': 'error',
                    'error': normalize_text(exc),
                }
            status_counts[inspection.get('inspection_status')] += 1
            inspected_files.append(inspection)
        extraction_rules = consolidate_html_key_value_rules(
            extraction_rules
        )
        if decorate_source_plan is not None:
            decorate_source_plan(
                source_item, inspected_files, extraction_rules
            )
        source_plans.append({
            **source_item,
            'files': inspected_files,
            'extraction_rules': extraction_rules,
            'review_status': 'pending',
        })
    source_manifest_path = Path(source_manifest_path).resolve()
    output_parent = Path(output_path).resolve().parent
    extraction_plan = {
        'stage': plan_stage,
        'city_context': city_context,
        'administrative_unit': administrative_unit,
        'government_source_file': Path(
            os.path.relpath(source_manifest_path, output_parent)
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


def _extract_table_raw_records(
    source_table,
    extraction_rule,
    source_item,
    terms,
):
    """按列映射提取二维表中的原始记录。"""
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
    fill_columns = {
        validate_positive_index(column_index, 'fill_down_columns')
        for column_index in (extraction_rule.get('fill_down_columns') or [])
    }
    required_values = [
        {
            'column': validate_positive_index(
                required_mapping.get('column'), 'required_cell_values.column'
            ),
            'value': normalize_text(required_mapping.get('value')),
        }
        for required_mapping in (
            extraction_rule.get('required_cell_values') or []
        )
        if isinstance(required_mapping, dict)
    ]
    excluded_rows = {
        validate_positive_index(row_index, 'exclude_rows')
        for row_index in (extraction_rule.get('exclude_rows') or [])
    }
    entries = _attribute_entries(extraction_rule)
    filled_values: dict[int, str] = {}
    raw_records = []
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
        ).join(part for part in name_parts if part)
        if not place_name or any(
            terms.is_place_header(name_part) for name_part in name_parts
        ):
            continue
        attributes = {
            field: _entry_table_value(entry, table_row)
            for field, entry in entries.items()
        }
        source_location = ' | '.join(
            _source_location_parts(
                extraction_rule['file'], source_table.get('location')
            )
            + [f'row {row_number}']
        )
        raw_records.append(_build_raw_record(
            place_name=place_name,
            original_address=read_table_cell(
                table_row, address_column
            ),
            attributes=attributes,
            rule=extraction_rule,
            source_reference=build_source_reference(
                source_item, source_location
            ),
            source_item=source_item,
            row=table_row,
        ))
    return raw_records


def _extract_html_css_raw_records(
    source_path,
    extraction_rule,
    source_item,
    terms,
):
    """按 CSS 选择器提取重复网页记录。"""
    from bs4 import BeautifulSoup

    row_selector = normalize_text(extraction_rule.get('row_selector'))
    name_selector = normalize_text(
        extraction_rule.get('place_name_selector')
    )
    if not row_selector or not name_selector:
        raise ValueError('html_css 规则缺少行或地点选择器')
    address_selector = normalize_text(
        extraction_rule.get('original_address_selector')
    )
    excluded_rows = set(extraction_rule.get('exclude_rows') or [])
    soup = BeautifulSoup(load_source_html(source_path), 'lxml')
    entries = _attribute_entries(extraction_rule)
    raw_records = []
    for row_number, element in enumerate(soup.select(row_selector), start=1):
        if row_number in excluded_rows:
            continue
        name_element = element.select_one(name_selector)
        place_name = normalize_text(
            name_element.get_text(' ', strip=True)
            if name_element is not None else ''
        )
        if not place_name or terms.is_place_header(place_name):
            continue
        address_element = (
            element.select_one(address_selector)
            if address_selector else None
        )
        attributes = {
            field: _entry_element_value(entry, element)
            for field, entry in entries.items()
        }
        source_location = (
            f'{source_path.name} | {row_selector} | row {row_number}'
        )
        raw_records.append(_build_raw_record(
            place_name=place_name,
            original_address=normalize_text(
                address_element.get_text(' ', strip=True)
                if address_element is not None else ''
            ),
            attributes=attributes,
            rule=extraction_rule,
            source_reference=build_source_reference(
                source_item, source_location
            ),
            source_item=source_item,
        ))
    return raw_records


def _extract_html_key_value_raw_records(
    source_path,
    extraction_rule,
    source_item,
    terms,
):
    """从纵向键值详情页提取一条原始记录。"""
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
        list(terms.place_headers) + list(terms.exact_place_headers),
    )
    if not place_name or terms.is_place_header(place_name):
        return []
    original_address = read_key_value_field(
        fields,
        extraction_rule.get('original_address_labels'),
        list(terms.address_headers),
    )
    entries = _attribute_entries(extraction_rule)
    attributes = {}
    for field, entry in entries.items():
        default_labels = []
        attribute_term = terms.attribute_index.get(field)
        if attribute_term is not None:
            default_labels = list(attribute_term.headers)
        attributes[field] = read_key_value_field(
            fields,
            entry.get('labels'),
            default_labels,
        ) or normalize_text(entry.get('value'))
    source_location = f'{source_path.name} | key-value table'
    return [_build_raw_record(
        place_name=place_name,
        original_address=original_address,
        attributes=attributes,
        rule=extraction_rule,
        source_reference=build_source_reference(
            source_item, source_location
        ),
        source_item=source_item,
    )]


def _extract_text_regex_raw_records(
    source_path,
    extraction_rule,
    source_item,
):
    """按命名正则从文本提取原始记录。"""
    pattern = re.compile(
        str(extraction_rule.get('pattern') or ''), re.MULTILINE
    )
    if 'place_name' not in pattern.groupindex:
        raise ValueError('text_regex 必须包含 place_name 命名组')
    entries = _attribute_entries(extraction_rule)
    raw_records = []
    for segment_text, source_location in extract_text_segments(
        source_path, extraction_rule.get('location') or {}
    ):
        for match in pattern.finditer(segment_text):
            matched_fields = match.groupdict()
            place_name = normalize_text(matched_fields.get('place_name'))
            if not place_name:
                continue
            attributes = {
                field: _entry_text_match_value(entry, matched_fields)
                for field, entry in entries.items()
            }
            raw_records.append(_build_raw_record(
                place_name=place_name,
                original_address=normalize_text(
                    matched_fields.get('original_address')
                ),
                attributes=attributes,
                rule=extraction_rule,
                source_reference=build_source_reference(
                    source_item, source_location
                ),
                source_item=source_item,
            ))
    return raw_records


def _scan_html_object_literals(text, marker_keys):
    """从 HTML/JS 文本中扫描可解析的平衡花括号对象。"""
    candidates = []
    index = 0
    while index < len(text):
        if text[index] != '{':
            index += 1
            continue
        depth = 1
        cursor = index + 1
        while cursor < len(text) and depth:
            if text[cursor] == '{':
                depth += 1
            elif text[cursor] == '}':
                depth -= 1
            cursor += 1
        if depth != 0:
            break
        candidate = text[index:cursor]
        try:
            item = json.loads(candidate)
        except (TypeError, ValueError):
            index += 1
            continue
        if isinstance(item, dict) and (
            not marker_keys
            or any(str(key) in candidate for key in marker_keys)
        ):
            candidates.append(item)
            index = cursor
        else:
            index += 1
    return candidates


def _load_object_items(source_path, extraction_rule):
    """按规则配置从 JSON/JSONP/HTML 对象中加载对象列表。"""
    object_format = str(
        extraction_rule.get('object_format') or 'json'
    ).strip()
    text = source_path.read_text(encoding='utf-8', errors='replace')
    if object_format == 'json':
        payload = json.loads(text)
    elif object_format == 'jsonp':
        jsonp_match = JSONP_PATTERN.match(text)
        if jsonp_match:
            payload = json.loads(jsonp_match.group(1))
        else:
            payload = json.loads(text)
    elif object_format == 'html_object_literal':
        return _scan_html_object_literals(
            text,
            list(extraction_rule.get('marker_keys') or []),
        )
    elif object_format == 'html_js_assignment':
        prefix = str(
            extraction_rule.get('assignment_id_prefix') or ''
        ).strip()
        if not prefix:
            raise ValueError(
                'html_js_assignment 规则缺少 assignment_id_prefix'
            )
        assignment_pattern = re.compile(
            re.escape(prefix) + r'(\d+)\.(\w+)="([^"]*)"'
        )
        grouped: dict[int, dict[str, str]] = {}
        for card_id, field_name, value in assignment_pattern.findall(text):
            grouped.setdefault(int(card_id), {})[field_name] = value
        return [
            grouped[card_id]
            for card_id in sorted(grouped, key=int)
        ]
    else:
        raise ValueError(f'不支持的 object_format：{object_format}')
    items = payload
    for container_key in list(extraction_rule.get('container_keys') or []):
        if not isinstance(items, dict):
            items = []
            break
        items = items.get(str(container_key)) or []
    if not isinstance(items, list):
        raise ValueError('object_list 容器必须解析为数组')
    return items


def _extract_object_list_raw_records(
    source_path,
    extraction_rule,
    source_item,
):
    """从 JSON/内嵌对象列表提取原始记录。"""
    place_keys = list(extraction_rule.get('place_name_keys') or [])
    address_keys = list(extraction_rule.get('original_address_keys') or [])
    if not place_keys:
        raise ValueError('object_list 规则缺少 place_name_keys')
    entries = _attribute_entries(extraction_rule)
    raw_records = []
    for row_number, item in enumerate(
        _load_object_items(source_path, extraction_rule), start=1
    ):
        if not isinstance(item, dict):
            continue
        place_name = next(
            (
                normalize_text(item[key])
                for key in place_keys
                if item.get(key) is not None
                and normalize_text(item.get(key))
            ),
            '',
        )
        if not place_name:
            continue
        original_address = next(
            (
                normalize_text(item[key])
                for key in address_keys
                if item.get(key) is not None
                and normalize_text(item.get(key))
            ),
            '',
        )
        attributes = {
            field: _entry_object_value(entry, item)
            for field, entry in entries.items()
        }
        source_location = f'{source_path.name} | row {row_number}'
        raw_records.append(_build_raw_record(
            place_name=place_name,
            original_address=original_address,
            attributes=attributes,
            rule=extraction_rule,
            source_reference=build_source_reference(
                source_item, source_location
            ),
            source_item=source_item,
        ))
    return raw_records


def _resolve_rule_source_files(
    source_dir: Path,
    source_plan: dict,
    extraction_rule: dict,
):
    """把单文件或文件模式规则限定到来源清单已登记的文件。"""
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
        raise ValueError(
            f'file_pattern 没有匹配已登记文件：{file_pattern}'
        )
    resolved_files = []
    for matched_name in matched_names:
        if matched_name not in declared_files:
            raise ValueError(f'提取规则引用未登记文件：{matched_name}')
        resolved_files.append((
            resolve_source_path(source_dir, matched_name),
            matched_name,
            normalize_text(
                declared_files[matched_name].get('source_url')
            ),
        ))
    return resolved_files


def _execute_rule(
    source_dir,
    source_plan,
    extraction_rule,
    table_cache,
    terms,
):
    """解析规则引用文件并执行，返回原始提取记录。"""
    raw_records = []
    rule_sources = _resolve_rule_source_files(
        source_dir, source_plan, extraction_rule
    )
    for source_path, source_file_name, source_url in rule_sources:
        effective_rule = dict(extraction_rule)
        effective_rule['file'] = source_file_name
        effective_rule.pop('file_pattern', None)
        source_item = _effective_source_plan(source_plan, source_url)
        rule_kind = extraction_rule.get('kind')
        if rule_kind in TABLE_RULE_KINDS:
            if source_path not in table_cache:
                table_cache[source_path] = load_source_tables(source_path)[0]
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
            raw_records.extend(_extract_table_raw_records(
                source_table, effective_rule, source_item, terms
            ))
        elif rule_kind == 'html_css':
            raw_records.extend(_extract_html_css_raw_records(
                source_path, effective_rule, source_item, terms
            ))
        elif rule_kind == 'html_key_value':
            raw_records.extend(_extract_html_key_value_raw_records(
                source_path, effective_rule, source_item, terms
            ))
        elif rule_kind == 'text_regex':
            raw_records.extend(_extract_text_regex_raw_records(
                source_path, effective_rule, source_item
            ))
        elif rule_kind in OBJECT_LIST_RULE_KINDS:
            raw_records.extend(_extract_object_list_raw_records(
                source_path, effective_rule, source_item
            ))
        else:
            raise ValueError(
                f'不支持的规则类型：{extraction_rule.get("kind")}'
            )
    return raw_records


def extract_government_records(
    plan_path: Path,
    *,
    plan_stage: str,
    terms: FieldTerms,
    build_address_records: Callable[[dict], list[dict]],
    skip_place_name: (
        Callable[[str], bool] | None
    ) = None,
) -> tuple[list[dict], dict[str, int], list[str]]:
    """执行已复核提取计划并返回场景构造的地址记录与指标。"""
    extraction_plan = read_json_payload(plan_path)
    if extraction_plan.get('stage') != plan_stage:
        raise ValueError(f'输入必须是 {plan_stage} JSON')
    government_source_path = (
        Path(plan_path).resolve().parent
        / normalize_text(extraction_plan.get('government_source_file'))
    ).resolve()
    source_dir = government_source_path.parent
    source_plans = extraction_plan.get('items')
    if not isinstance(source_plans, list):
        raise ValueError('提取计划必须包含 items 数组')
    table_cache: dict[Path, list[dict]] = {}
    records: list[dict] = []
    error_messages: list[str] = []
    reviewed_count = 0
    skipped_count = 0
    approved_count = 0
    raw_item_count = 0
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
            error_messages.append(
                f'{source_title} 尚未完成提取计划复核'
            )
            continue
        reviewed_count += 1
        extraction_rules = [
            rule for rule in (source_plan.get('extraction_rules') or [])
            if isinstance(rule, dict) and rule.get('approved') is True
        ]
        if not extraction_rules:
            error_messages.append(f'{source_title} 没有已批准的提取规则')
            continue
        for rule_index, extraction_rule in enumerate(
            extraction_rules, start=1
        ):
            approved_count += 1
            try:
                raw_records = _execute_rule(
                    source_dir,
                    source_plan,
                    extraction_rule,
                    table_cache,
                    terms,
                )
                source_records = []
                for raw_item in raw_records:
                    raw_item_count += 1
                    if (
                        skip_place_name is not None
                        and skip_place_name(raw_item['place_name'])
                    ):
                        continue
                    source_records.extend(
                        build_address_records(raw_item)
                    )
                if not source_records:
                    raise ValueError(
                        '规则没有从 '
                        f'{extraction_rule.get("file") or "来源文件"} '
                        '提取到任何记录'
                    )
                records.extend(source_records)
            except Exception as exc:  # noqa: BLE001 - 单规则失败不中断
                error_messages.append(
                    f'{source_title} 规则 {rule_index}：'
                    f'{normalize_text(exc)}'
                )
    metrics = {
        'source_count': len(source_plans),
        'reviewed_source_count': reviewed_count,
        'skipped_source_count': skipped_count,
        'approved_rule_count': approved_count,
        'raw_item_count': raw_item_count,
        'record_count': len(records),
        'error_count': len(error_messages),
    }
    return records, metrics, error_messages


__all__ = (
    'extract_government_records',
    'inspect_government_source',
)
