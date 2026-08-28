"""读取 Excel 来源。"""

from pathlib import Path
from typing import Any

from .common import extract_dataframe_rows


def extract_spreadsheet_tables(source_path: Path) -> list[dict[str, Any]]:
    """读取 Excel 的全部工作表。"""
    import pandas as pd

    tables = []
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
