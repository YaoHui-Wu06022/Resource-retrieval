"""读取带原生文字层的 PDF 来源。"""

import contextlib
import io
from pathlib import Path
from typing import Any

from .common import normalize_text


def extract_pdf_tables(
    source_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读取 PDF 页级文字并提取可检测的表格。"""
    import pymupdf

    tables = []
    pages = []
    total_characters = 0
    replacement_characters = 0
    with pymupdf.open(source_path) as document:
        for page_number, page in enumerate(document, start=1):
            page_text = normalize_text(page.get_text('text', sort=True))
            total_characters += len(page_text)
            replacement_characters += page_text.count('\ufffd')
            page_metadata = {
                'page': page_number,
                'text_character_count': len(page_text),
                'image_count': len(page.get_images(full=True)),
                'text_preview': page_text[:400],
            }
            pages.append(page_metadata)
            if len(page_text) < 20:
                continue
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                    io.StringIO()
                ):
                    detected_tables = page.find_tables().tables
            except Exception as exc:
                page_metadata['table_detection_error'] = normalize_text(exc)
                continue
            for table_index, detected_table in enumerate(detected_tables, start=1):
                rows = [
                    [normalize_text(cell_value) for cell_value in table_row]
                    for table_row in (detected_table.extract() or [])
                ]
                if rows:
                    tables.append({
                        'kind': 'pdf_table',
                        'location': {
                            'page': page_number,
                            'table_index': table_index,
                        },
                        'rows': rows,
                    })
    if total_characters < max(100, len(pages) * 5):
        status = 'needs_vision'
        tables = []
    elif replacement_characters / max(total_characters, 1) > 0.01:
        status = 'text_mapping_issue'
    else:
        status = 'ready'
    return tables, {
        'inspection_status': status,
        'vision_reason': 'no_native_text' if status == 'needs_vision' else '',
        'page_count': len(pages),
        'text_character_count': total_characters,
        'pages': pages,
    }
