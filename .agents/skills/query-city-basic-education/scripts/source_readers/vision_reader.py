"""读取视觉模型生成的结构化识别结果。"""

import json
from pathlib import Path
from typing import Any

from . import normalize_text


def extract_vision_tables(
    source_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把视觉识别结果中的页级文本行读取为二维表格。"""
    vision_payload = json.loads(source_path.read_text(encoding='utf-8-sig'))
    if vision_payload.get('stage') != 'vision_source_result':
        raise ValueError('视觉识别文件必须是 vision_source_result JSON')
    pages = vision_payload.get('pages')
    if not isinstance(pages, list):
        raise ValueError('视觉识别文件必须包含 pages 数组')
    tables = []
    for page in pages:
        page_number = page.get('page')
        rows = [
            [normalize_text(cell_text) for cell_text in row]
            for row in (page.get('rows') or [])
            if isinstance(row, list)
        ]
        if rows:
            tables.append({
                'kind': 'vision_table',
                'location': {'page': page_number},
                'rows': rows,
            })
    return tables, {
        'inspection_status': 'ready' if tables else 'vision_result_empty',
        'source_file': normalize_text(vision_payload.get('source_file')),
        'selected_pages': [table['location']['page'] for table in tables],
    }
