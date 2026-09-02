"""统一的查询结果工作簿格式。"""

import os
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pathlib import Path
import tempfile
from urllib.parse import urlparse
import re

from .address.common import (
    MAP_MATCH_STATUS_VALUES,
    format_map_match_status,
)


HEADER_FILL = PatternFill(fill_type='solid', fgColor='1F4E78')
HEADER_FONT = Font(name='Microsoft YaHei', size=10, bold=True, color='FFFFFF')
BODY_FONT = Font(name='Microsoft YaHei', size=10, color='000000')
HEADER_BORDER = Border(
    left=Side(style='thin', color='9EADBA'),
    right=Side(style='thin', color='9EADBA'),
    top=Side(style='thin', color='9EADBA'),
    bottom=Side(style='thin', color='9EADBA'),
)
ROW_BORDER = Border(bottom=Side(style='thin', color='D9E2F3'))
CENTER_ALIGNMENT = Alignment(horizontal='center', vertical='center')
WRAPPED_ALIGNMENT = Alignment(
    horizontal='center',
    vertical='center',
    wrap_text=True,
)
HEADER_ALIGNMENT = Alignment(
    horizontal='center',
    vertical='center',
    wrap_text=True,
)
ADDRESS_OUTPUT_HEADERS = (
    '地址',
    '地址获取方式',
    '地图匹配状态',
    '信息来源',
)
ADDRESS_OUTPUT_WIDTHS = (42, 14, 16, 50)
SOURCE_URL_PATTERN = re.compile(r'^https?://[^\s|]+', re.IGNORECASE)
ROW_REFERENCE_PATTERN = re.compile(r'^row\s+\d+$', re.IGNORECASE)
DATE_CELL_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}')


def extend_address_output_columns(headers, column_widths):
    """在领域列后追加通用地址结果列及默认列宽。"""
    return list(headers) + list(ADDRESS_OUTPUT_HEADERS), list(column_widths) + list(ADDRESS_OUTPUT_WIDTHS)


def build_address_output_values(
    address_record,
    official_source_label,
    map_source_label,
):
    """从已处理地址记录构造通用地址结果列值。"""
    final_source = address_record.get('final_address_source')
    source_label = map_source_label if final_source == 'map' else official_source_label
    return [
        str(address_record.get('final_address') or '').strip(),
        source_label,
        format_map_match_status(address_record.get('map_match_status')),
        format_source_reference(address_record.get('source_reference')),
    ]


def extract_source_url(source_reference):
    """从来源定位文本开头提取网页地址。"""
    match = SOURCE_URL_PATTERN.match(str(source_reference or '').strip())
    return match.group(0) if match else ''


def format_source_reference(source_reference):
    """规范化来源展示文本，保留网址、文件名和行号等定位信息。"""
    parts = [part.strip() for part in str(source_reference or '').split('|') if part.strip()]
    source_url = extract_source_url(source_reference)
    file_name = parts[1] if len(parts) > 1 else ''
    row_reference = next((part for part in parts[2:] if ROW_REFERENCE_PATTERN.fullmatch(part)), '')
    return ' | '.join(part for part in (source_url, file_name, row_reference) if part)


def format_date_cell(value, fallback=''):
    """规范日期单元格为 YYYY-MM-DD；空值使用 fallback。"""
    return str(value or '').strip() or fallback


def write_workbook_atomically(workbook, output_path, validate):
    """原子保存工作簿并在替换前执行校验。"""
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=output.stem + '.',
        suffix='.tmp.xlsx',
        dir=output.parent,
    )
    os.close(handle)
    try:
        workbook.save(temporary)
        validate(temporary)
        os.replace(temporary, output)
    finally:
        workbook.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def add_source_hyperlinks(sheet, source_column):
    """为指定来源列中的网页文本添加超链接。"""
    from copy import copy
    from urllib.parse import urlparse

    for source_column_cells in sheet.iter_cols(
        min_col=source_column, max_col=source_column, min_row=2,
        max_row=sheet.max_row,
    ):
        for cell in source_column_cells:
            value = str(cell.value or '').strip()
            url = extract_source_url(value)
            parsed = urlparse(url)
            if not url or parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                continue
            cell.hyperlink = url
            hyperlink_font = copy(cell.font)
            hyperlink_font.color = '0563C1'
            hyperlink_font.underline = 'single'
            cell.font = hyperlink_font


def validate_common_worksheet(
    worksheet,
    headers,
    expected_row_count,
    address_header='地址',
    source_header='信息来源',
    match_header='地图匹配状态',
    acquisition_header='地址获取方式',
):
    """校验地址结果表的公共字段、样式和来源链接。"""
    headers = tuple(headers)
    if [cell.value for cell in worksheet[1]] != list(headers):
        raise ValueError(f'{worksheet.title}工作表字段不正确')
    if worksheet.max_row - 1 != expected_row_count:
        raise ValueError(f'{worksheet.title}工作表记录数不正确')
    if worksheet.sheet_view.showGridLines:
        raise ValueError(f'{worksheet.title}工作表未关闭网格线')
    address_column = headers.index(address_header) + 1
    source_column = headers.index(source_header) + 1
    match_column = headers.index(match_header) + 1
    acquisition_column = headers.index(acquisition_header) + 1
    for row_index, row in enumerate(worksheet.iter_rows(
        min_row=1, max_row=worksheet.max_row,
        min_col=1, max_col=len(headers),
    ), start=1):
        for cell in row:
            if cell.alignment.horizontal != 'center' or cell.alignment.vertical != 'center':
                raise ValueError(f'{worksheet.title}存在未居中的单元格')
            expected_wrap = row_index == 1 or cell.column == address_column
            if bool(cell.alignment.wrap_text) != expected_wrap:
                raise ValueError(f'{worksheet.title}的自动换行格式不正确')
            if cell.alignment.indent not in {None, 0, 0.0}:
                raise ValueError(f'{worksheet.title}不得设置缩进')
        if row_index == 1:
            continue
        if not str(worksheet.cell(row_index, address_column).value or '').strip():
            raise ValueError(f'{worksheet.title}存在空地址')
        acquisition_value = str(worksheet.cell(row_index, acquisition_column).value or '').strip()
        if acquisition_value not in {'官网提取', '地图信息', '政府资料', '高德地图'}:
            raise ValueError(f'{worksheet.title}存在无效地址获取方式')
        match_value = str(worksheet.cell(row_index, match_column).value or '').strip()
        valid_labels = {format_map_match_status(value) for value in MAP_MATCH_STATUS_VALUES}
        if match_value not in valid_labels:
            raise ValueError(f'{worksheet.title}存在无效地图匹配状态')
        source_cell = worksheet.cell(row_index, source_column)
        if not str(source_cell.value or '').strip():
            raise ValueError(f'{worksheet.title}存在空信息来源')
        url = extract_source_url(source_cell.value)
        if url.startswith(('http://', 'https://')) and not source_cell.hyperlink:
            raise ValueError(f'{worksheet.title}的信息来源没有可点击链接')


def populate_table_worksheet(
    sheet, sheet_name, headers, rows, column_widths
):
    """向工作表写入查询结果并应用统一格式。"""
    headers = tuple(headers)
    column_widths = tuple(column_widths)
    if not headers:
        raise ValueError('表头不能为空')
    if len(column_widths) != len(headers):
        raise ValueError('列宽数量必须与表头列数一致')

    sheet.title = sheet_name
    sheet.sheet_view.showGridLines = False
    sheet.append(headers)

    for row in rows:
        if len(row) != len(headers):
            raise ValueError('数据行列数必须与表头列数一致')
        sheet.append(tuple(row))

    last_column = get_column_letter(len(headers))
    wrapped_columns = {
        index for index, header in enumerate(headers, 1) if header == '地址'
    }
    sheet.auto_filter.ref = f'A1:{last_column}{sheet.max_row}'
    sheet.freeze_panes = 'A2'

    for index, width in enumerate(column_widths, 1):
        if width <= 0:
            raise ValueError('列宽必须大于 0')
        sheet.column_dimensions[get_column_letter(index)].width = width

    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = HEADER_BORDER
        cell.alignment = HEADER_ALIGNMENT
    sheet.row_dimensions[1].height = 28

    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY_FONT
            cell.border = ROW_BORDER
            cell.alignment = (
                WRAPPED_ALIGNMENT
                if cell.column in wrapped_columns
                else CENTER_ALIGNMENT
            )
        if not wrapped_columns:
            sheet.row_dimensions[row[0].row].height = 22

    return sheet


def build_table_workbook(sheet_name, headers, rows, column_widths):
    """构建带统一格式的单表工作簿。"""
    workbook = Workbook()
    populate_table_worksheet(
        workbook.active,
        sheet_name,
        headers,
        rows,
        column_widths,
    )
    return workbook
