#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试基础教育学校地址记录构造规则。"""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import extract_school_records as EXTRACTOR  # noqa: E402
import inspect_government_source as INSPECTOR  # noqa: E402
import normalize_school_records as NORMALIZER  # noqa: E402


class CampusAddressTests(unittest.TestCase):
    """验证明确标签地址的拆分边界。"""

    def test_single_labeled_campus_is_appended_to_name(self):
        """单个园区标签也应进入地点名称。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例幼儿园', '龙福路园区：海珠区龙福路二巷3号'
            ),
            [('示例幼儿园龙福路园区', '海珠区龙福路二巷3号')],
        )

    def test_abbreviated_complete_middle_school_is_normalized(self):
        """完中应规范为完全中学。"""
        self.assertEqual(NORMALIZER.normalize_school_type('完中'), '完全中学')

    def test_technical_schools_are_normalized_as_technical_colleges(self):
        """技师学院和技工学校应统一规范为技工院校。"""
        self.assertEqual(
            NORMALIZER.normalize_school_type('技师学院'), '技工院校'
        )
        self.assertEqual(
            NORMALIZER.normalize_school_type('技工学校'), '技工院校'
        )

    def test_chinese_name_line_break_space_is_removed(self):
        """中文校名因换行产生的内部空格应被移除。"""
        self.assertEqual(
            NORMALIZER.normalize_place_name_text('广州市明珠高级中学有限 公司'),
            '广州市明珠高级中学有限公司',
        )

    def test_latin_name_space_is_preserved(self):
        """拉丁文字中的正常单词空格应继续保留。"""
        self.assertEqual(
            NORMALIZER.normalize_place_name_text('Guangzhou Foreign School'),
            'Guangzhou Foreign School',
        )

    def test_inline_campuses_are_split_and_grade_notes_removed(self):
        """连续校区地址应拆行并移除年级说明。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例中学',
                '东校区：广州市海珠区测试路1号（初一、初二）'
                '校本部：广州市海珠区测试路2号（初三）',
            ),
            [
                ('示例中学东校区', '广州市海珠区测试路1号'),
                ('示例中学校本部', '广州市海珠区测试路2号'),
            ],
        )

    def test_unlabeled_address_is_unchanged(self):
        """没有明确标签的普通地址不得拆分或改名。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例学校', '广州市海珠区测试路1号'
            ),
            [('示例学校', '广州市海珠区测试路1号')],
        )

    def test_slash_separated_labeled_campuses_are_split(self):
        """斜杠分隔且各自带标签的校区地址应拆成多条。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例小学',
                '天河区甲路1号（东校区）/天河区乙路2号（西校区）',
            ),
            [
                ('示例小学东校区', '天河区甲路1号'),
                ('示例小学西校区', '天河区乙路2号'),
            ],
        )

    def test_adjacent_labeled_campuses_are_split(self):
        """无分隔符但连续带标签的校区地址应拆成多条。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例中学',
                '天河区甲路1号（沙河校区）天河区乙路2号（棠德校区）',
            ),
            [
                ('示例中学沙河校区', '天河区甲路1号'),
                ('示例中学棠德校区', '天河区乙路2号'),
            ],
        )

    def test_parenthesized_prefix_campuses_are_split(self):
        """括号前置的明确校区标签应拆成多条。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例学校',
                '（长堤校区）越秀区甲路1号；（石公祠校区）越秀区乙路2号',
            ),
            [
                ('示例学校长堤校区', '越秀区甲路1号'),
                ('示例学校石公祠校区', '越秀区乙路2号'),
            ],
        )

    def test_duplicate_school_types_are_merged(self):
        """同名同址记录应合并学校类型。"""
        school_records = [
            {
                'place_name': '示例学校',
                'original_address': '',
                'attributes': {'school_type': '小学'},
            },
            {
                'place_name': '示例学校',
                'original_address': '',
                'attributes': {'school_type': '初中'},
            },
        ]
        unique_records, duplicate_count = (
            NORMALIZER.deduplicate_school_records(school_records)
        )
        self.assertEqual(duplicate_count, 1)
        self.assertEqual(unique_records[0]['attributes']['school_type'], '小学、初中')

    def test_duplicate_school_keeps_record_with_latest_publication_date(self):
        """同名同址记录应以发布日期最新的来源作为基础记录。"""
        school_records = [
            {
                'place_name': '示例学校',
                'original_address': '越秀区甲路1号',
                'source_reference': '较早来源',
                'attributes': {
                    'school_type': '小学',
                    'publication_date': '2025-08-01',
                },
            },
            {
                'place_name': '示例学校',
                'original_address': '越秀区甲路1号',
                'source_reference': '最新来源',
                'attributes': {
                    'school_type': '初中',
                    'publication_date': '2026-08-01',
                },
            },
        ]

        unique_records, duplicate_count = (
            NORMALIZER.deduplicate_school_records(school_records)
        )

        self.assertEqual(duplicate_count, 1)
        self.assertEqual(unique_records[0]['source_reference'], '最新来源')
        self.assertEqual(
            unique_records[0]['attributes']['publication_date'], '2026-08-01'
        )
        self.assertEqual(unique_records[0]['attributes']['school_type'], '小学、初中')

    def test_school_type_is_inferred_from_nonzero_plan_columns(self):
        """非零招生人数列应组合为对应学段。"""
        column_mappings = [
            {'column': 4, 'value': '小学'},
            {'column': 6, 'value': '初中'},
        ]
        self.assertEqual(
            EXTRACTOR.classify_school_type_from_presence(
                ['1', '示例学校', '5', '220', '6', '280'], column_mappings
            ),
            '小学、初中',
        )

    def test_zero_enrollment_does_not_remove_school_record(self):
        """招生人数为零只影响类型推断，不得删除学校。"""
        table = {
            'location': {'sheet': '学校名录'},
            'rows': [
                ['学校名称', '小学招生人数', '初中招生人数'],
                ['示例学校', '0', '0'],
            ],
        }
        rule = {
            'file': '来源.xlsx',
            'data_start_row': 2,
            'place_name_columns': [1],
            'school_type_presence_columns': [
                {'column': 2, 'value': '小学'},
                {'column': 3, 'value': '初中'},
            ],
        }

        school_records = EXTRACTOR.extract_table_records(
            table, rule, {}, '越秀区'
        )

        self.assertEqual(len(school_records), 1)
        self.assertEqual(school_records[0]['place_name'], '示例学校')
        self.assertEqual(school_records[0]['attributes']['school_type'], '')

    def test_extract_table_records_can_keep_only_address_rows(self):
        """联系方式表应只保留显式标记为地址的行。"""
        table = {
            'location': {'table_index': 1},
            'rows': [
                ['示例小学', '电话', '123'],
                ['示例小学', '地址', '荔湾区甲路1号'],
            ],
        }
        rule = {
            'file': '来源.html',
            'data_start_row': 1,
            'place_name_columns': [1],
            'original_address_column': 3,
            'required_cell_values': [{'column': 2, 'value': '地址'}],
        }
        school_records = EXTRACTOR.extract_table_records(
            table, rule, {}, '荔湾区'
        )
        self.assertEqual(len(school_records), 1)
        self.assertEqual(
            school_records[0]['original_address'], '荔湾区甲路1号'
        )

    def test_source_publication_date_is_preserved(self):
        """来源发布日期应保留，缺失时应使用当天日期。"""
        dated_record = EXTRACTOR.build_school_record(
            '示例小学', '荔湾区甲路1号', '小学', '公办',
            {'publication_date': '2026-08-01'}, '来源.html | row 1', '荔湾区'
        )
        blank_record = EXTRACTOR.build_school_record(
            '示例中学', '荔湾区乙路2号', '初中', '公办',
            {}, '来源.html | row 2', '荔湾区'
        )
        self.assertEqual(
            dated_record['attributes']['publication_date'], '2026-08-01'
        )
        self.assertEqual(
            blank_record['attributes']['publication_date'], date.today().isoformat()
        )


class SourceManifestTests(unittest.TestCase):
    """验证行政单位来源清单的公共字段约定。"""

    def setUp(self):
        """构造包含一个直接下级行政单位的城市上下文。"""
        self.administrative_unit = {
            'name': '越秀区',
            'adcode': '440104',
            'level': 'district',
        }
        self.city_context = {
            'stage': 'city_context',
            'input_city': '广州',
            'city_name': '广州市',
            'province_name': '广东省',
            'subdivisions': [self.administrative_unit],
        }

    def build_source_manifest(self):
        """返回使用统一顶层字段的最小来源清单。"""
        return {
            'stage': 'basic_education_government_source',
            'city_context': self.city_context,
            'administrative_unit': self.administrative_unit,
            'processing_status': 'no_official_source',
            'school_type_coverage': {
                '幼儿园': 'no_official_source',
                '小学': 'no_official_source',
                '初中': 'no_official_source',
                '高中': 'no_official_source',
            },
            'items': [],
        }

    def test_common_source_manifest_fields_are_accepted(self):
        """来源清单应使用 stage、city_context 和 items。"""
        city_context, administrative_unit, items = (
            INSPECTOR.validate_source_manifest(self.build_source_manifest())
        )
        self.assertEqual(city_context, self.city_context)
        self.assertEqual(administrative_unit, self.administrative_unit)
        self.assertEqual(items, [])

    def test_unregistered_source_manifest_fields_are_rejected(self):
        """未登记字段和旧顶层字段不得混用。"""
        for obsolete_field, obsolete_value in (
            ('city', '广州市'),
            ('status', 'completed'),
            ('sources', []),
            ('unexpected_field', ''),
        ):
            with self.subTest(field=obsolete_field):
                source_manifest = self.build_source_manifest()
                source_manifest[obsolete_field] = obsolete_value
                with self.assertRaisesRegex(ValueError, obsolete_field):
                    INSPECTOR.validate_source_manifest(source_manifest)

    def test_administrative_unit_must_come_from_city_context(self):
        """行政单位必须原样来自城市上下文的 subdivisions。"""
        source_manifest = self.build_source_manifest()
        source_manifest['administrative_unit'] = {
            'name': '天河区',
            'adcode': '440106',
            'level': 'district',
        }
        with self.assertRaisesRegex(ValueError, 'administrative_unit'):
            INSPECTOR.validate_source_manifest(source_manifest)

    def test_completed_source_manifest_requires_full_coverage_and_items(self):
        """completed 不得与空来源或覆盖缺口同时出现。"""
        source_manifest = self.build_source_manifest()
        source_manifest['processing_status'] = 'completed'
        source_manifest['school_type_coverage'] = {
            school_type: 'covered'
            for school_type in ('幼儿园', '小学', '初中', '高中')
        }
        with self.assertRaisesRegex(ValueError, 'completed'):
            INSPECTOR.validate_source_manifest(source_manifest)

    def test_source_item_does_not_repeat_detectable_file_format(self):
        """来源项不要求 Agent 重复填写可由文件识别的格式。"""
        source_manifest = self.build_source_manifest()
        source_manifest['processing_status'] = 'partial'
        source_manifest['school_type_coverage']['幼儿园'] = 'covered'
        source_manifest['items'] = [{
            'source_title': '越秀区幼儿园名录',
            'publisher': '越秀区教育局',
            'publication_date': '2026-08-01',
            'landing_page_url': 'https://www.example.gov.cn/notice/1',
            'content_url': 'https://www.example.gov.cn/files/list.xlsx',
            'covered_school_types': ['幼儿园'],
            'contains_address': True,
            'local_files': ['越秀区幼儿园名录.xlsx'],
        }]
        _, _, items = INSPECTOR.validate_source_manifest(source_manifest)
        self.assertEqual(items, source_manifest['items'])

    def test_build_extraction_plan_preserves_city_scope(self):
        """inspect 输出应继续原样传递城市上下文和行政单位。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            input_path = source_dir / 'government_source.json'
            output_path = source_dir / 'extraction_plan.json'
            INSPECTOR.write_json_object(
                input_path, self.build_source_manifest()
            )
            extraction_plan, exit_code = INSPECTOR.build_extraction_plan(
                input_path, output_path
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(extraction_plan['city_context'], self.city_context)
        self.assertEqual(
            extraction_plan['administrative_unit'], self.administrative_unit
        )
        self.assertEqual(
            extraction_plan['government_source_file'],
            'government_source.json',
        )
        self.assertEqual(extraction_plan['items'], [])


if __name__ == '__main__':
    unittest.main()
