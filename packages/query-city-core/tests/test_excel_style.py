"""查询结果工作簿格式测试。"""

import unittest

from query_city_core.excel_style import build_table_workbook


class TableWorkbookTests(unittest.TestCase):
    def test_builds_a_centered_filterable_table(self):
        workbook = build_table_workbook(
            '示例表',
            ('名称', '编号'),
            [('甲', '001'), ('乙', '002')],
            (20, 12),
        )
        try:
            sheet = workbook['示例表']
            self.assertEqual(sheet.auto_filter.ref, 'A1:B3')
            self.assertEqual(sheet.freeze_panes, 'A2')
            self.assertFalse(sheet.sheet_view.showGridLines)
            self.assertEqual(sheet.column_dimensions['A'].width, 20)
            self.assertEqual(sheet.column_dimensions['B'].width, 12)
            self.assertEqual(sheet.row_dimensions[1].height, 28)
            self.assertEqual(sheet.row_dimensions[2].height, 22)
            self.assertEqual(sheet['A1'].fill.fgColor.rgb[-6:], '1F4E78')
            self.assertTrue(sheet['A1'].font.bold)
            self.assertEqual(sheet['A1'].font.color.rgb[-6:], 'FFFFFF')
            self.assertEqual(sheet['A2'].alignment.horizontal, 'center')
            self.assertEqual(sheet['A2'].alignment.vertical, 'center')
            self.assertEqual(sheet['A2'].border.bottom.style, 'thin')
            self.assertEqual(sheet['A2'].border.bottom.color.rgb[-6:], 'D9E2F3')
        finally:
            workbook.close()

    def test_rejects_widths_not_matching_headers(self):
        with self.assertRaisesRegex(ValueError, '列宽数量'):
            build_table_workbook('示例表', ('名称',), [], ())

    def test_wraps_address_column_and_leaves_row_height_automatic(self):
        workbook = build_table_workbook(
            '示例表',
            ('名称', '地址'),
            [('甲', '广州市天河区示例大道一百二十三号')],
            (20, 24),
        )
        try:
            sheet = workbook['示例表']
            self.assertFalse(sheet['A2'].alignment.wrap_text)
            self.assertTrue(sheet['B2'].alignment.wrap_text)
            self.assertIsNone(sheet.row_dimensions[2].height)
        finally:
            workbook.close()
