"""来源表格读取共用的单元格与 DataFrame 转换。"""

from typing import Any

from . import normalize_text


def normalize_cell_text(cell_value: Any) -> str:
    """清理单元格文本并保留有意义的换行。"""
    if cell_value is None:
        return ''
    lines = [
        normalize_text(line)
        for line in str(cell_value).replace('\xa0', ' ').splitlines()
    ]
    return '\n'.join(line for line in lines if line)


def extract_dataframe_rows(dataframe: Any) -> list[list[str]]:
    """把 DataFrame 转为纯文本二维行。"""
    return [
        [normalize_cell_text(cell_value) for cell_value in table_row]
        for table_row in dataframe.fillna('').values.tolist()
    ]
