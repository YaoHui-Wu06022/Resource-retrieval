"""测试 preview 对图片来源与其派生 vision.json 的配对处理。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from school_government_flow import preview_extraction_plan  # noqa: E402


class PreviewVisionPairingTest(unittest.TestCase):
    """验证图片名录经 vision.json 派生后不再被 preview 误报。"""

    def _build_plan(self, temporary_dir, approved=True):
        source_dir = Path(temporary_dir)
        (source_dir / 'government_source.json').write_text(
            '{}', encoding='utf-8'
        )
        vision_rows = [
            ['学校', '地址', '联系电话'],
            ['广州市某小学', '某区某路1号', '12345678'],
        ]
        (source_dir / '名录.png.vision.json').write_text(json.dumps({
            'stage': 'vision_source_result',
            'source_file': '名录.png',
            'pages': [{'page': 1, 'rows': vision_rows}],
        }, ensure_ascii=False), encoding='utf-8')
        rules = []
        if approved:
            rules.append({
                'file': '名录.png.vision.json',
                'kind': 'vision_table',
                'location': {'page': 1},
                'header_row': 1,
                'data_start_row': 2,
                'data_end_row': None,
                'place_name_columns': [1],
                'place_name_separator': '',
                'original_address_column': 2,
                'attribute_fields': [
                    {'field': 'school_type', 'column': None,
                     'value': '小学', 'selector': '', 'labels': []},
                    {'field': 'school_nature', 'column': None,
                     'value': '公办', 'selector': '', 'labels': []},
                ],
                'fill_down_columns': [],
                'required_cell_values': [],
                'exclude_rows': [],
                'approved': True,
            })
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
                'source_title': '图片名录',
                'review_status': 'ready',
                'local_files': ['名录.png'],
                'derived_files': ['名录.png.vision.json'],
                'extraction_rules': rules,
            }],
        }, ensure_ascii=False), encoding='utf-8')
        return plan_path

    def test_paired_vision_image_passes_preview(self):
        """原图无规则但有派生 vision 规则时应通过复核。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            plan_path = self._build_plan(temporary_dir)
            payload, exit_code = preview_extraction_plan(plan_path)
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['error_count'], 0)
            self.assertEqual(payload['candidate_row_count'], 1)
            self.assertEqual(payload['covered_row_count'], 1)
            self.assertEqual(payload['uncovered_row_count'], 0)
            self.assertEqual(payload['overlap_row_count'], 0)
            image_report = next(
                report for report in payload['files']
                if report['file'] == '名录.png'
            )
            self.assertIn('skipped_reason', image_report)
            vision_report = next(
                report for report in payload['files']
                if report['file'] == '名录.png.vision.json'
            )
            self.assertEqual(vision_report['covered_row_count'], 1)

    def test_missing_paired_vision_rule_still_errors(self):
        """没有派生 vision 规则时图片仍应报缺少已批准规则。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            plan_path = self._build_plan(temporary_dir, approved=False)
            payload, exit_code = preview_extraction_plan(plan_path)
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload['error_count'], 2)
            self.assertTrue(any(
                error.startswith('名录.png')
                for error in payload['errors']
            ))


if __name__ == '__main__':
    unittest.main()
