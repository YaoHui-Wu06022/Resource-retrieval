"""读取 Excel 与 CSV 来源。"""

from pathlib import Path
from typing import Any

from .tables import extract_dataframe_rows


def extract_spreadsheet_tables(source_path: Path) -> list[dict[str, Any]]:
    """读取 Excel 的全部工作表或单个 CSV 文件。"""
    import pandas as pd

    tables = []
    if source_path.suffix.lower() == '.csv':
        tables.append({
            'kind': 'sheet',
            'location': {'sheet': source_path.stem},
            'rows': extract_dataframe_rows(_read_csv_dataframe(source_path)),
        })
        return tables
    with pd.ExcelFile(source_path) as workbook:
        for sheet_name in workbook.sheet_names:
            dataframe = pd.read_excel(
                workbook,
                sheet_name=sheet_name,
                header=None,
                keep_default_na=False,
            )
            tables.append({
                'kind': 'sheet',
                'location': {'sheet': sheet_name},
                'rows': extract_dataframe_rows(dataframe),
            })
    return tables


def _read_csv_dataframe(source_path: Path):
    """按 UTF-8 优先、GB18030 兜底读取 CSV。"""
    import pandas as pd

    common_options = {
        'header': None,
        'keep_default_na': False,
        'dtype': str,
    }
    try:
        return pd.read_csv(source_path, encoding='utf-8-sig', **common_options)
    except UnicodeDecodeError:
        return pd.read_csv(source_path, encoding='gb18030', **common_options)
