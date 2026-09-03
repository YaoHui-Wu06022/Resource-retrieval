"""测试视觉模型结构化结果读取。"""

import json
import tempfile
import unittest
from pathlib import Path

from query_city_core.official.readers import (
    detect_source_format,
    load_source_tables,
)
from query_city_core.official.readers.vision_reader import (
    merge_vision_table_rows,
    parse_vision_table_rows,
)


class VisionReaderTest(unittest.TestCase):
    """验证视觉识别结果能够进入表格提取链路。"""

    def test_parse_vision_table_rows_removes_code_fence(self):
        """模型输出 Markdown 代码块时应能解析出二维数组。"""
        rows = parse_vision_table_rows(
            '```json\n[["学校", "地址"], ["甲小学", "甲路1号"]]\n```'
        )
        self.assertEqual(rows, [['学校', '地址'], ['甲小学', '甲路1号']])

    def test_merge_vision_table_rows_keeps_header_once(self):
        """分段转录合并时只保留一次表头并按行去重。"""
        merged = merge_vision_table_rows([
            [['学校', '地址'], ['甲小学', '甲路1号']],
            [['学校', '地址'], ['甲小学', '甲路1号'], ['乙小学', '乙路2号']],
        ])
        self.assertEqual(merged, [
            ['学校', '地址'],
            ['甲小学', '甲路1号'],
            ['乙小学', '乙路2号'],
        ])

    def test_vision_json_is_loaded_as_page_tables(self):
        """视觉派生文件应按页读取为 vision_table。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / '名录.vision.json'
            source_path.write_text(json.dumps({
                'stage': 'vision_source_result',
                'source_file': '名录.png',
                'pages': [{
                    'page': 1,
                    'rows': [['学校', '地址'], ['甲小学', '甲路1号']],
                }],
            }, ensure_ascii=False), encoding='utf-8')
            self.assertEqual(detect_source_format(source_path), 'vision')
            tables, metadata = load_source_tables(source_path)
            self.assertEqual(tables[0]['kind'], 'vision_table')
            self.assertEqual(tables[0]['location'], {'page': 1})
            self.assertEqual(metadata['inspection_status'], 'ready')


if __name__ == '__main__':
    unittest.main()
