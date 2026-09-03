"""测试无视觉能力时显式跳过纯图像政府来源。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from school_government_flow import extract_school_records  # noqa: E402


class VisionExtractRecordsTest(unittest.TestCase):
    """验证视觉来源显式跳过时会生成合法的空地址记录集。"""

    def test_no_vision_source_can_be_explicitly_skipped(self):
        """无视觉能力时应允许显式跳过纯图像来源。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            (source_dir / 'government_source.json').write_text(
                '{}', encoding='utf-8'
            )
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
                'government_source_file': 'government_source.json',
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
            self.assertEqual(payload['metrics']['original_address_count'], 0)
            self.assertEqual(
                payload['metrics']['missing_original_address_count'], 0
            )


if __name__ == '__main__':
    unittest.main()
