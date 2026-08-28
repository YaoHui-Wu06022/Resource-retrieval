"""统一的查询结果工作簿格式。"""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


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
