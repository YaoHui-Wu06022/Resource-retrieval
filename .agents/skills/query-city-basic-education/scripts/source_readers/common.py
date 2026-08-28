"""提供来源读取器共用的文本和表格转换。"""

import re
from typing import Any


def normalize_text(raw_text: Any) -> str:
    """清理来源文本中的空白。"""
    if raw_text is None:
        return ''
    return re.sub(r'\s+', ' ', str(raw_text).replace('\xa0', ' ')).strip()


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
