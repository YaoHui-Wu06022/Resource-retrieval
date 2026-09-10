#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 review.py 页范围展开、视觉表头推断与 PDF 表缓存。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import review  # noqa: E402


class ReviewHelperTest(unittest.TestCase):
    """验证复核工具的展开与缓存逻辑。"""

    def test_expand_page_specs_range(self):
        """字符串页范围应展开为逐页 location。"""
        specs = review.expand_page_specs({
            'pages': '15-17',
            'name_cols': [3],
        })
        self.assertEqual(
            [spec['location'] for spec in specs],
            [15, 16, 17],
        )
        self.assertTrue(all('pages' not in spec for spec in specs))

    def test_expand_page_specs_keeps_single(self):
        """没有 pages 字段的规则原样保留。"""
        spec = {'location': 2, 'kind': 'vision_table'}
        self.assertEqual(review.expand_page_specs(spec), [spec])

    def test_vision_page_start_meta_detects_header(self):
        """首页含表头时 data_start_row=2，续页直接数据时为 1。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            vision_path = root / '名录.pdf.vision.json'
            vision_path.write_text(json.dumps({
                'stage': 'vision_source_result',
                'pages': [
                    {
                        'page': 16,
                        'rows': [['7', '街道', '学校名称', '地址']],
                    },
                    {
                        'page': 15,
                        'rows': [['序号', '街道', '单位', '地址']],
                    },
                ],
            }, ensure_ascii=False), encoding='utf-8')
            plan_path = root / 'extraction_plan.json'
            self.assertEqual(
                review.vision_page_start_meta(
                    plan_path, '名录.pdf.vision.json', 15
                ),
                (1, 2),
            )
            self.assertEqual(
                review.vision_page_start_meta(
                    plan_path, '名录.pdf.vision.json', 16
                ),
                (0, 1),
            )

    def test_cached_pdf_tables_reuses_parse(self):
        """相同文件 mtime 下只解析一次，结果写入临时缓存。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            pdf_path = Path(temporary_dir) / 'sample.pdf'
            pdf_path.write_bytes(b'%PDF-1.4 fake')
            sample = [{'location': {'page': 1}, 'rows': [['学校']]}]
            with mock.patch.object(
                review,
                'load_source_tables',
                return_value=(sample, {'inspection_status': 'ready'}),
            ) as load_mock:
                first = review._cached_pdf_tables(pdf_path)
                second = review._cached_pdf_tables(pdf_path)
            self.assertEqual(first, sample)
            self.assertEqual(second, sample)
            self.assertEqual(load_mock.call_count, 1)


if __name__ == '__main__':
    unittest.main()
