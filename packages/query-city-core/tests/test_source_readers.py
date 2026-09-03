"""测试官方来源读取器的格式边界。"""

import tempfile
import unittest
from pathlib import Path

from query_city_core.official.readers import (
    detect_source_format,
    load_source_tables,
)


class SourceReaderTests(unittest.TestCase):
    """覆盖 PDF 文字层和图片视觉识别边界。"""

    def test_blank_pdf_requires_vision(self):
        """没有原生文字层的 PDF 应进入视觉识别状态。"""
        import pymupdf

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / '扫描件.pdf'
            document = pymupdf.open()
            document.new_page()
            document.save(pdf_path)
            document.close()
            tables, metadata = load_source_tables(pdf_path)
        self.assertEqual(tables, [])
        self.assertEqual(metadata['inspection_status'], 'needs_vision')
        self.assertEqual(metadata['vision_reason'], 'no_native_text')

    def test_image_waits_for_model_vision(self):
        """图片应作为最后补充来源等待视觉模型。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / '名单.png'
            image_path.touch()
            tables, metadata = load_source_tables(image_path)
        self.assertEqual(detect_source_format(image_path), 'image')
        self.assertEqual(tables, [])
        self.assertEqual(metadata['inspection_status'], 'needs_vision')
        self.assertEqual(metadata['vision_reason'], 'image_source')

    def test_detect_supports_xlsm_and_csv(self):
        """宏工作簿和 CSV 都按电子表格读取。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            xlsm_path = Path(temp_dir) / '名录.xlsm'
            csv_path = Path(temp_dir) / '名录.csv'
            xlsm_path.touch()
            csv_path.touch()
        self.assertEqual(detect_source_format(xlsm_path), 'spreadsheet')
        self.assertEqual(detect_source_format(csv_path), 'spreadsheet')

    def test_csv_table_read(self):
        """CSV 应读取为单一 sheet 表格。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / '幼儿园名录.csv'
            csv_path.write_text(
                '学校名称,学校地址\n示例幼儿园,广州市天河区示例路1号\n',
                encoding='utf-8',
            )
            tables, metadata = load_source_tables(csv_path)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]['kind'], 'sheet')
        self.assertEqual(tables[0]['location'], {'sheet': '幼儿园名录'})
        self.assertEqual(tables[0]['rows'][1][0], '示例幼儿园')
        self.assertEqual(metadata['inspection_status'], 'ready')

    def test_csv_gbk_fallback(self):
        """GBK 编码的 CSV 应兜底读取成功。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / '名录.csv'
            csv_path.write_bytes(
                '学校名称,学校地址\n示例幼儿园,广州市天河区示例路1号\n'.encode('gbk')
            )
            tables, _ = load_source_tables(csv_path)
        self.assertEqual(tables[0]['rows'][1][0], '示例幼儿园')


if __name__ == '__main__':
    unittest.main()
