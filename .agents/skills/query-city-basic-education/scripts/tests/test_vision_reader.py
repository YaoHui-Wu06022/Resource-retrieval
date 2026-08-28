"""测试视觉模型结构化结果读取。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_readers import detect_source_format, load_source_tables  # noqa: E402
from build_school_records import extract_school_records  # noqa: E402


class VisionReaderTest(unittest.TestCase):
    """验证视觉识别结果能够进入表格提取链路。"""

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

    def test_no_vision_source_can_be_explicitly_skipped(self):
        """无视觉能力时应允许显式跳过纯图像来源。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            (source_dir / 'sources.json').write_text('{}', encoding='utf-8')
            plan_path = source_dir / 'extraction_plan.json'
            plan_path.write_text(json.dumps({
                'stage': 'basic_education_extraction_plan',
                'city_context': {
                    'stage': 'city_context',
                    'input_city': '广州市',
                    'city_name': '广州市',
                    'province_name': '广东省',
                    'subdivisions': [],
                },
                'administrative_unit': {'name': '测试区'},
                'source_manifest': 'sources.json',
                'items': [{
                    'source_title': '扫描名录',
                    'review_status': 'skipped',
                    'skip_reason': 'no_vision_capability',
                    'files': [{
                        'file': '扫描名录.pdf',
                        'inspection_status': 'needs_vision',
                    }],
                    'extraction_rules': [],
                }],
            }, ensure_ascii=False), encoding='utf-8')
            payload, exit_code = extract_school_records(plan_path)
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['stage'], 'address_records')
            self.assertEqual(payload['metrics']['skipped_source_count'], 1)


if __name__ == '__main__':
    unittest.main()
