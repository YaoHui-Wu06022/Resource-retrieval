"""官方来源记录提取的通用工具。"""

import re
from typing import Any

from ..readers import (
    detect_source_format,
    load_source_html,
    normalize_text,
)


def validate_positive_index(index_value, field_name):
    """校验规则中的一基索引。"""
    if not isinstance(index_value, int) or index_value < 1:
        raise ValueError(f'{field_name} 必须是从 1 开始的整数')
    return index_value


def is_table_location_match(source_table, extraction_rule):
    """判断二维表是否对应提取规则。"""
    return source_table['kind'] == extraction_rule.get('kind') and source_table[
        'location'
    ] == (extraction_rule.get('location') or {})


def build_source_reference(source_record, source_location):
    """组合来源链接和文件内定位。"""
    source_url = normalize_text(
        source_record.get('content_url')
        or source_record.get('landing_page_url')
    )
    return (
        f'{source_url} | {source_location}' if source_url else source_location
    )


def normalize_key_value_label(label_text):
    """统一详情页纵向字段名称。"""
    return re.sub(r'[\s（）()：:、/\\_\-]+', '', normalize_text(label_text))


def read_key_value_field(fields, configured_labels, default_labels):
    """按已复核标签或默认官方表头读取详情页字段。"""
    labels = configured_labels or default_labels
    if not isinstance(labels, (list, tuple)):
        raise ValueError('html_key_value 字段标签必须是数组')
    for label in labels:
        field_value = fields.get(normalize_key_value_label(label))
        if field_value:
            return field_value
    return ''


def extract_text_segments(source_path, source_location):
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
