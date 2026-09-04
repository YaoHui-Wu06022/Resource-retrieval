"""测试 preview 按规则定位表独立统计并应用 required_cell_values。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from school_government_flow import preview_extraction_plan  # noqa: E402


class PreviewRuleAccountingTest(unittest.TestCase):
    """验证 preview 不再把不同表的行号当作同一行空间。"""

    def _write_plan(
        self,
        temporary_dir,
        vision_file,
        vision_rows,
        rules,
    ):
        source_dir = Path(temporary_dir)
        (source_dir / 'government_source.json').write_text(
            '{}', encoding='utf-8'
        )
        (source_dir / vision_file).write_text(json.dumps({
            'stage': 'vision_source_result',
            'source_file': vision_file,
            'pages': vision_rows,
        }, ensure_ascii=False), encoding='utf-8')
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
                'source_title': '多表名录',
                'review_status': 'ready',
                'local_files': [vision_file],
                'extraction_rules': rules,
            }],
        }, ensure_ascii=False), encoding='utf-8')
        return plan_path

    def _basic_rule(self, file_name, page, name_column=1):
        return {
            'file': file_name,
            'kind': 'vision_table',
            'location': {'page': page},
            'header_row': 1,
            'data_start_row': 2,
            'data_end_row': None,
            'place_name_columns': [name_column],
            'place_name_separator': '',
            'original_address_column': None,
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
        }

    def test_multiple_tables_do_not_report_false_overlap(self):
        """同一文件不同表的同名行号不应计为重叠。"""
        file_name = '名录.png.vision.json'
        with tempfile.TemporaryDirectory() as temporary_dir:
            plan_path = self._write_plan(
                temporary_dir,
                file_name,
                [
                    {'page': 1, 'rows': [
                        ['学校', '地址'],
                        ['A小学', '甲路1号'],
                        ['B小学', '甲路2号'],
                    ]},
                    {'page': 2, 'rows': [
                        ['学校', '地址'],
                        ['C小学', '乙路3号'],
                    ]},
                ],
                [
                    self._basic_rule(file_name, 1),
                    self._basic_rule(file_name, 2),
                ],
            )
            payload, exit_code = preview_extraction_plan(plan_path)
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['error_count'], 0)
            self.assertEqual(payload['candidate_row_count'], 3)
            self.assertEqual(payload['covered_row_count'], 3)
            self.assertEqual(payload['uncovered_row_count'], 0)
            self.assertEqual(payload['overlap_row_count'], 0)

    def test_required_cell_values_filter_applied_in_counts(self):
        """键值表只统计满足 required_cell_values 的地址行。"""
        file_name = '联系方式.png.vision.json'
        rule = self._basic_rule(file_name, 1, name_column=2)
        rule['original_address_column'] = 6
        rule['required_cell_values'] = [
            {'column': 5, 'value': '地址'}
        ]
        with tempfile.TemporaryDirectory() as temporary_dir:
            plan_path = self._write_plan(
                temporary_dir,
                file_name,
                [{'page': 1, 'rows': [
                    ['序号', '学校', '办别', '性质', '联系方式', '内容'],
                    ['1', 'A小学', '公办', '小学', '热线电话', '123'],
                    ['1', 'A小学', '公办', '小学', '地址', '甲路1号'],
                    ['2', 'B小学', '公办', '小学', '热线电话', '456'],
                    ['2', 'B小学', '公办', '小学', '地址', '乙路2号'],
                ]}],
                [rule],
            )
            payload, exit_code = preview_extraction_plan(plan_path)
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['error_count'], 0)
            self.assertEqual(payload['candidate_row_count'], 2)
            self.assertEqual(payload['covered_row_count'], 2)
            self.assertEqual(payload['uncovered_row_count'], 0)
            self.assertEqual(payload['overlap_row_count'], 0)
            self.assertEqual(payload['type_counts'].get('小学'), 2)


if __name__ == '__main__':
    unittest.main()
