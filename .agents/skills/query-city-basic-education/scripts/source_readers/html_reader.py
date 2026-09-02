"""读取 HTML 和 Word 来源。"""

import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import normalize_text
from .tables import extract_dataframe_rows


def find_soffice_path() -> str | None:
    """查找用于读取 Word 的 LibreOffice。"""
    soffice_path = shutil.which('soffice')
    if soffice_path:
        return soffice_path
    candidate_paths = (
        Path(r'C:\Program Files\LibreOffice\program\soffice.exe'),
        Path(r'C:\Program Files (x86)\LibreOffice\program\soffice.exe'),
    )
    return next(
        (str(path) for path in candidate_paths if path.is_file()),
        None,
    )


def convert_word_to_html(source_path: Path) -> str:
    """把 Word 临时转换为 HTML 文本。"""
    from bs4 import BeautifulSoup

    soffice_path = find_soffice_path()
    if not soffice_path:
        raise RuntimeError('解析 Word 需要 LibreOffice，但当前环境未找到 soffice')
    with tempfile.TemporaryDirectory(prefix='basic-education-word-') as temp_dir:
        conversion_result = subprocess.run(
            [
                soffice_path,
                '--headless',
                '--convert-to',
                'html',
                '--outdir',
                temp_dir,
                str(source_path),
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
            check=False,
        )
        converted_path = Path(temp_dir) / f'{source_path.stem}.html'
        if conversion_result.returncode != 0 or not converted_path.is_file():
            error_message = normalize_text(
                conversion_result.stderr or conversion_result.stdout
            )
            raise RuntimeError(
                f'Word 转换失败：{error_message or source_path.name}'
            )
        soup = BeautifulSoup(converted_path.read_bytes(), 'lxml')
    return str(soup)


def load_source_html(source_path: Path, file_format: str) -> str:
    """读取网页或经转换的 Word HTML。"""
    if file_format == 'word':
        return convert_word_to_html(source_path)
    from bs4 import BeautifulSoup

    return str(BeautifulSoup(source_path.read_bytes(), 'lxml'))


def extract_html_tables(
    source_path: Path, file_format: str
) -> list[dict[str, Any]]:
    """读取 HTML 或 Word 中的全部表格。"""
    import pandas as pd

    try:
        frames = pd.read_html(
            io.StringIO(load_source_html(source_path, file_format)),
            header=None,
            flavor='lxml',
        )
    except ValueError:
        frames = []
    return [
        {
            'kind': 'table',
            'location': {'table_index': index},
            'rows': extract_dataframe_rows(dataframe),
        }
        for index, dataframe in enumerate(frames, start=1)
    ]
