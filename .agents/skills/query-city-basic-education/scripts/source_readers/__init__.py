"""按来源格式选择对应读取器。"""

import re
from pathlib import Path
from typing import Any


def normalize_text(raw_text: Any) -> str:
    """清理来源文本中的空白，折叠为单个空格。"""
    if raw_text is None:
        return ''
    return re.sub(r'\s+', ' ', str(raw_text).replace('\xa0', ' ')).strip()


# normalize_text 必须先于读取器导入定义，供读取器相对导入，避免包级循环导入。
from .html_reader import extract_html_tables, load_source_html as load_html_document
from .image_reader import inspect_image_source
from .pdf_reader import extract_pdf_tables
from .spreadsheet_reader import extract_spreadsheet_tables
from .vision_reader import extract_vision_tables


FORMAT_BY_SUFFIX = {
    '.doc': 'word',
    '.docx': 'word',
    '.htm': 'html',
    '.html': 'html',
    '.jpeg': 'image',
    '.jpg': 'image',
    '.pdf': 'pdf',
    '.png': 'image',
    '.webp': 'image',
    '.xls': 'spreadsheet',
    '.xlsx': 'spreadsheet',
    '.xlsm': 'spreadsheet',
    '.csv': 'spreadsheet',
}


def detect_source_format(source_path: Path) -> str:
    """根据扩展名识别来源格式。"""
    if source_path.name.lower().endswith('.vision.json'):
        return 'vision'
    file_format = FORMAT_BY_SUFFIX.get(source_path.suffix.lower())
    if not file_format:
        raise ValueError(f'不支持的来源格式：{source_path.name}')
    return file_format


def load_source_html(source_path: Path) -> str:
    """读取 HTML 或 Word 的统一 HTML 文本。"""
    file_format = detect_source_format(source_path)
    if file_format not in {'html', 'word'}:
        raise ValueError(f'来源不是 HTML 或 Word：{source_path.name}')
    return load_html_document(source_path, file_format)


def load_source_tables(
    source_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按格式把来源读取为二维表格。"""
    file_format = detect_source_format(source_path)
    if file_format in {'html', 'word'}:
        tables = extract_html_tables(source_path, file_format)
        return tables, {'inspection_status': 'ready' if tables else 'manual_review'}
    if file_format == 'spreadsheet':
        return extract_spreadsheet_tables(source_path), {
            'inspection_status': 'ready'
        }
    if file_format == 'pdf':
        return extract_pdf_tables(source_path)
    if file_format == 'vision':
        return extract_vision_tables(source_path)
    return inspect_image_source(source_path)
