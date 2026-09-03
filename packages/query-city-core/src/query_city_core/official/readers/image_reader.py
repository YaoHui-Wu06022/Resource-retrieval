"""标记需要视觉模型识别的图片来源。"""

from pathlib import Path
from typing import Any


def inspect_image_source(
    source_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把图片标记为等待视觉模型识别。"""
    return [], {
        'inspection_status': 'needs_vision',
        'vision_reason': 'image_source',
        'size_bytes': source_path.stat().st_size,
    }
