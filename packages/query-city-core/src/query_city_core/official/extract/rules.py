"""官方来源表头规则推断与来源文件检查。"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..readers import (
    detect_source_format,
    load_source_html,
    load_source_tables,
    normalize_text,
)


class AttributeTerm:
    """场景属性词表：字段名由 Skill 提供，公共层不解释语义。"""

    def __init__(
        self,
        field,
        headers=(),
        label_text='',
        fill_down=False,
    ):
        self.field = str(field)
        self.headers = tuple(headers)
        self.label_text = label_text
        self.fill_down = bool(fill_down)


class FieldTerms:
    """场景字段词表：把表头识别与重复容器评分与业务词隔离。"""

    def __init__(
        self,
        place_headers=(),
        exact_place_headers=(),
        address_headers=(),
        attribute_terms=(),
        place_marker_pattern='',
        address_marker_pattern='',
        excluded_place_label_pattern='',
    ):
        self.place_headers = tuple(place_headers)
        self.exact_place_headers = tuple(exact_place_headers)
        self.address_headers = tuple(address_headers)
        self.attribute_terms = tuple(attribute_terms)
        self.attribute_index = {
            term.field: term
            for term in self.attribute_terms
        }
        self.place_marker_pattern = re.compile(place_marker_pattern)
        self.address_marker_pattern = re.compile(address_marker_pattern)
        self.excluded_place_label_pattern = re.compile(
            excluded_place_label_pattern
        )

    def is_place_header(self, header_text):
        """判断表头是否为机构名称。"""
        header = normalize_header(header_text)
        return header in self.exact_place_headers or any(
            keyword in header for keyword in self.place_headers
        )

    def is_address_header(self, header_text):
        """判断表头是否为地址。"""
        header = normalize_header(header_text)
        return any(keyword in header for keyword in self.address_headers)

    def attribute_matches_header(self, attribute_term, header_text):
        """判断表头是否属于某个场景属性。"""
        header = normalize_header(header_text)
        return any(keyword in header for keyword in attribute_term.headers)

    def attribute_field_matches_header(self, field, header_text):
        """按字段名判断表头是否命中。"""
        term = self.attribute_index.get(field)
        return bool(
            term and self.attribute_matches_header(term, header_text)
        )

    def matching_attribute_headers(self, header_row):
        """返回每个属性命中的列索引（1 基）。"""
        matches = {}
        for term in self.attribute_terms:
            columns = [
                index
                for index, header_text in enumerate(header_row, start=1)
                if self.attribute_matches_header(term, header_text)
            ]
            if columns:
                matches[term.field] = columns
        return matches

    def attribute_headers_matching_texts(self, labels):
        """从纵向键值标签中识别每个属性命中的原文标签。"""
        matches = {}
        for term in self.attribute_terms:
            matched = [
                label
                for label in labels
                if self.attribute_matches_header(term, label)
            ]
            if matched:
                matches[term.field] = list(dict.fromkeys(matched))
        return matches


def normalize_header(header_text):
    """统一表头文本以便匹配字段。"""
    return re.sub(
        r'[\s（）()：:、/\\_\-]+', '', normalize_text(header_text)
    ).lower()


def read_table_cell(table_row, column_index):
    """按一基列号安全读取单元格。"""
    if column_index is None:
        return ''
    if not isinstance(column_index, int) or column_index < 1:
        raise ValueError('列号必须是从 1 开始的整数')
    return table_row[column_index - 1] if column_index <= len(table_row) else ''


def infer_table_rule(
    table_rows,
    file_name,
    structure_kind,
    location,
    terms,
):
    """根据常见表头生成待复核规则。"""
    for header_index, header_row in enumerate(table_rows[:10], start=1):
        place_columns = [
            index for index, header_text in enumerate(header_row, start=1)
            if terms.is_place_header(header_text)
        ]
        if not place_columns:
            continue
        address_columns = [
            index for index, header_text in enumerate(header_row, start=1)
            if terms.is_address_header(header_text)
        ]
        attribute_columns = terms.matching_attribute_headers(header_row)
        fill_down_columns = []
        if address_columns and any(
            not read_table_cell(data_row, place_columns[0])
            and read_table_cell(data_row, address_columns[0])
            for data_row in table_rows[header_index:]
        ):
            fill_down_columns.append(place_columns[0])
        attribute_fields = []
        for term in terms.attribute_terms:
            columns = attribute_columns.get(term.field) or []
            column = columns[0] if columns else None
            if (
                term.fill_down
                and column
                and column not in fill_down_columns
                and any(
                    not read_table_cell(data_row, column)
                    and read_table_cell(data_row, place_columns[0])
                    for data_row in table_rows[header_index:]
                )
            ):
                fill_down_columns.append(column)
            attribute_fields.append({
                'field': term.field,
                'column': column,
                'value': '',
                'selector': '',
                'labels': [],
            })
        return {
            'file': file_name,
            'kind': structure_kind,
            'location': location,
            'header_row': header_index,
            'data_start_row': header_index + 1,
            'data_end_row': None,
            'place_name_columns': place_columns,
            'place_name_separator': '',
            'original_address_column': (
                address_columns[0] if address_columns else None
            ),
            'attribute_fields': attribute_fields,
            'fill_down_columns': fill_down_columns,
            'required_cell_values': [],
            'exclude_rows': [],
            'approved': False,
        }
    return None


def infer_html_key_value_rule(table_rows, file_name, terms):
    """识别详情页中纵向排列的字段和值。"""
    key_value_rows = [
        row for row in table_rows
        if len(row) >= 2 and normalize_text(row[0]) and normalize_text(row[1])
    ]
    labels = [normalize_text(row[0]) for row in key_value_rows]
    place_labels = [label for label in labels if terms.is_place_header(label)]
    address_labels = [
        label for label in labels if terms.is_address_header(label)
    ]
    if not place_labels or not address_labels:
        return None
    attribute_labels = terms.attribute_headers_matching_texts(labels)
    attribute_fields = [
        {
            'field': term.field,
            'labels': list(attribute_labels.get(term.field) or []),
            'value': '',
            'selector': '',
            'column': None,
        }
        for term in terms.attribute_terms
    ]
    return {
        'file': file_name,
        'kind': 'html_key_value',
        'place_name_labels': list(dict.fromkeys(place_labels)),
        'original_address_labels': list(dict.fromkeys(address_labels)),
        'attribute_fields': attribute_fields,
        'approved': False,
    }


def consolidate_html_key_value_rules(suggested_rules):
    """把同一目录下结构相同的详情页规则合并为一个文件模式。"""
    grouped_rules = defaultdict(list)
    passthrough_rules = []
    for suggested_rule in suggested_rules:
        if suggested_rule.get('kind') != 'html_key_value':
            passthrough_rules.append(suggested_rule)
            continue
        rule_signature = {
            key: value for key, value in suggested_rule.items()
            if key != 'file'
        }
        grouped_rules[json.dumps(
            rule_signature, ensure_ascii=False, sort_keys=True
        )].append(suggested_rule)
    for rule_group in grouped_rules.values():
        if len(rule_group) == 1:
            passthrough_rules.extend(rule_group)
            continue
        rule_files = [Path(rule['file']) for rule in rule_group]
        parent_paths = {rule_file.parent.as_posix() for rule_file in rule_files}
        suffixes = {rule_file.suffix.lower() for rule_file in rule_files}
        if len(parent_paths) != 1 or len(suffixes) != 1:
            passthrough_rules.extend(rule_group)
            continue
        consolidated_rule = {
            key: value for key, value in rule_group[0].items()
            if key != 'file'
        }
        parent_path = next(iter(parent_paths))
        file_pattern = f'*{next(iter(suffixes))}'
        consolidated_rule['file_pattern'] = (
            f'{parent_path}/{file_pattern}'
            if parent_path != '.' else file_pattern
        )
        passthrough_rules.append(consolidated_rule)
    return passthrough_rules


def collect_repeated_html_candidates(source_path, file_name, terms):
    """检查网页或 Word 中重复的机构地址容器。"""
    from bs4 import BeautifulSoup
    from soupsieve import escape

    soup = BeautifulSoup(load_source_html(source_path), 'lxml')
    groups = defaultdict(list)
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
                bool(terms.place_marker_pattern.search(cell_text))
                and not terms.excluded_place_label_pattern.search(cell_text)
                for cell_text in column
            )
            for column in columns
        ]
        address_scores = [
            sum(
                bool(terms.address_marker_pattern.search(cell_text))
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
        attribute_fields = []
        for term in terms.attribute_terms:
            selector = ''
            if term.label_text:
                candidate = (
                    f'li:-soup-contains("{term.label_text}")'
                )
                if sum(
                    element.select_one(candidate) is not None
                    for element in elements[:8]
                ) >= threshold:
                    selector = candidate
            attribute_fields.append({
                'field': term.field,
                'selector': selector,
                'value': '',
                'column': None,
                'labels': [],
            })
        suggested_rules.append({
            'file': file_name,
            'kind': 'html_css',
            'row_selector': tag + ''.join(f'.{escape(name)}' for name in classes),
            'place_name_selector': f':scope > :nth-child({place_index + 1})',
            'original_address_selector': (
                f':scope > :nth-child({address_index + 1})'
            ),
            'attribute_fields': attribute_fields,
            'exclude_rows': [],
            'approved': False,
        })
    repeated_blocks.sort(key=lambda block: block['count'], reverse=True)
    text_preview = normalize_text(
        (soup.body or soup).get_text(' ', strip=True)
    )[:800]
    return repeated_blocks[:15], suggested_rules, text_preview


def inspect_source_file(source_path, file_name, terms):
    """检查一个来源文件并生成规则建议。"""
    tables, inspection_metadata = load_source_tables(source_path)
    file_format = detect_source_format(source_path)
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
        if file_format == 'html':
            key_value_rule = infer_html_key_value_rule(rows, file_name, terms)
            if key_value_rule:
                suggested_rules.append(key_value_rule)
                continue
        suggested_rule = infer_table_rule(
            rows, file_name, table['kind'], table['location'], terms
        )
        if suggested_rule:
            suggested_rules.append(suggested_rule)
    repeated_blocks = []
    text_preview = ''
    if file_format == 'html':
        repeated_blocks, repeated_rules, text_preview = (
            collect_repeated_html_candidates(source_path, file_name, terms)
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


def resolve_source_path(source_dir, file_name):
    """解析并限制来源文件位于来源目录内。"""
    source_path = (source_dir / file_name).resolve()
    try:
        source_path.relative_to(source_dir)
    except ValueError as exc:
        raise ValueError(f'来源文件越出来源目录：{file_name}') from exc
    if not source_path.is_file():
        raise FileNotFoundError(f'来源文件不存在：{file_name}')
    return source_path
