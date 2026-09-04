"""读取结构化识别结果（MinerU 等生成的 vision_source_result）。"""

import json
import re
from pathlib import Path
from typing import Any

from . import normalize_text


_VISION_JSON_FENCE_PATTERN = re.compile(
    r'^```(?:json)?|```$', re.MULTILINE
)


def inspect_image_source(
    source_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把图片标记为需要外部结构化识别（MinerU 视觉解析）。"""
    return [], {
        'inspection_status': 'needs_vision',
        'vision_reason': 'image_source',
        'size_bytes': source_path.stat().st_size,
    }


def parse_vision_table_rows(model_text: str) -> list[list[str]]:
    """解析模型输出的 JSON 二维数组。"""
    cleaned = _VISION_JSON_FENCE_PATTERN.sub(
        '', str(model_text or '').strip()
    )
    start = cleaned.find('[')
    end = cleaned.rfind(']')
    if start < 0 or end <= start:
        raise ValueError('视觉模型输出中没有 JSON 数组')
    rows = json.loads(cleaned[start:end + 1])
    if not isinstance(rows, list) or any(
        not isinstance(row, list) for row in rows
    ):
        raise ValueError('视觉模型输出不是二维数组')
    return [
        [normalize_text(cell_text) for cell_text in row]
        for row in rows
    ]


def merge_vision_table_rows(
    segment_rows: list[list[list[str]]],
) -> list[list[str]]:
    """合并分段结果并只保留一次表头。"""
    merged = []
    header = None
    seen = set()
    for rows in segment_rows:
        if not rows:
            continue
        if header is None:
            header = tuple(rows[0])
            merged.append(rows[0])
        for row in rows[1:]:
            if tuple(row) == tuple(header or []):
                continue
            key = json.dumps(row, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def extract_vision_tables(
    source_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把结构化识别结果中的页级文本行读取为二维表格。"""
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
