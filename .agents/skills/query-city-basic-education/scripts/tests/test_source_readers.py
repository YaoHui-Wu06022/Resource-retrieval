#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试基础教育来源读取器的格式边界。"""

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_readers import (  # noqa: E402
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


if __name__ == '__main__':
    unittest.main()
