"""读取并调用视觉模型生成结构化识别结果。"""

import base64
import io
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from ...env_utils import read_env_value
from . import normalize_text


DEFAULT_VISION_API_BASE_URL = (
    'https://dashscope.aliyuncs.com/compatible-mode/v1'
)
DEFAULT_VISION_MODEL = 'qwen3.8-27b'
_VISION_SYSTEM_PROMPT = (
    '你是官方表格转录器。只负责把图片中的表格逐行转录成 JSON，'
    '不解释、不推断、不合并空白单元格、不翻译列名。'
)
_VISION_USER_PROMPT = (
    '请把图片中的表格按原样转录为 JSON 二维数组：第一行是表头，'
    '之后每行是一条记录。保留所有列，包括空白单元格。'
    '忽略图片中表格以外的文字。只输出 JSON，不要 Markdown 代码块。'
)
_VISION_JSON_FENCE_PATTERN = re.compile(
    r'^```(?:json)?|```$', re.MULTILINE
)


def inspect_image_source(
    source_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把图片标记为等待视觉模型识别。"""
    return [], {
        'inspection_status': 'needs_vision',
        'vision_reason': 'image_source',
        'size_bytes': source_path.stat().st_size,
    }


def split_vision_image_segments(
    source_path: Path,
    max_chunk_height: int = 700,
    overlap: int = 60,
) -> list[Any]:
    """把图片放大并切成带重叠的竖向片段供模型识别。"""
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(
            '视觉转录需要 Pillow，请先安装依赖'
        ) from error
    with Image.open(source_path) as source:
        width, height = source.size
        if width < 1200:
            source = source.resize(
                (width * 2, height * 2), Image.LANCZOS
            )
        segments = []
        top = 0
        while top < source.height:
            bottom = min(top + max_chunk_height * 2, source.height)
            segments.append(source.crop((0, top, source.width, bottom)))
            if bottom >= source.height:
                break
            top = bottom - overlap * 2
    return segments


def encode_vision_image_segment(segment: Any) -> str:
    """把 PIL 图像片段编码为 base64 data URL。"""
    buffer = io.BytesIO()
    segment.save(buffer, format='PNG')
    return (
        'data:image/png;base64,'
        + base64.b64encode(buffer.getvalue()).decode('ascii')
    )


def call_vision_completion(
    api_key: str,
    base_url: str,
    model: str,
    image_data_url: str,
    reasoning_effort: str,
) -> str:
    """调用 OpenAI 兼容视觉接口并返回模型文本。"""
    payload = {
        'model': model,
        'temperature': 0,
        'messages': [
            {'role': 'system', 'content': _VISION_SYSTEM_PROMPT},
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': _VISION_USER_PROMPT},
                    {
                        'type': 'image_url',
                        'image_url': {'url': image_data_url},
                    },
                ],
            },
        ],
    }
    if reasoning_effort:
        payload['reasoning_effort'] = reasoning_effort
    request = urllib.request.Request(
        f'{base_url.rstrip("/")}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode('utf-8'))
    return str(body['choices'][0]['message']['content'] or '')


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


def read_vision_config() -> tuple[str, str, str, str]:
    """从进程环境或 .env 读取视觉模型配置。"""
    api_key = read_env_value('VISION_API_KEY')
    if not api_key:
        raise RuntimeError('缺少 VISION_API_KEY 环境变量或 .env 配置')
    base_url = (
        read_env_value('VISION_API_BASE_URL')
        or DEFAULT_VISION_API_BASE_URL
    )
    model = read_env_value('VISION_MODEL') or DEFAULT_VISION_MODEL
    reasoning_effort = read_env_value('VISION_REASONING_EFFORT')
    return api_key, base_url, model, reasoning_effort


def transcribe_image_to_vision_result(
    source_image_path: Path,
    output_path: Path,
    max_chunk_height: int = 700,
) -> dict[str, Any]:
    """调用视觉模型把官方表格图片转录为 vision_source_result。"""
    source_image_path = Path(source_image_path).resolve()
    output_path = Path(output_path).resolve()
    api_key, base_url, model, reasoning_effort = read_vision_config()
    segments = split_vision_image_segments(
        source_image_path, max_chunk_height
    )
    segment_rows = []
    for segment in segments:
        data_url = encode_vision_image_segment(segment)
        model_text = call_vision_completion(
            api_key,
            base_url,
            model,
            data_url,
            reasoning_effort,
        )
        segment_rows.append(parse_vision_table_rows(model_text))
    rows = merge_vision_table_rows(segment_rows)
    payload = {
        'stage': 'vision_source_result',
        'source_file': source_image_path.name,
        'pages': [{'page': 1, 'rows': rows}],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return payload


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
