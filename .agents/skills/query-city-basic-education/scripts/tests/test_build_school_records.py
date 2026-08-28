#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试基础教育学校地址记录构造规则。"""

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'build_school_records.py'
SPEC = importlib.util.spec_from_file_location(
    'basic_education_build_school_records', SCRIPT_PATH
)
EXTRACTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXTRACTOR
SPEC.loader.exec_module(EXTRACTOR)


class CampusAddressTests(unittest.TestCase):
    """验证明确标签地址的拆分边界。"""

    def test_single_labeled_campus_is_appended_to_name(self):
        """单个园区标签也应进入地点名称。"""
        self.assertEqual(
            EXTRACTOR.split_explicit_campus_addresses(
                '示例幼儿园', '龙福路园区：海珠区龙福路二巷3号'
            ),
            [('示例幼儿园龙福路园区', '海珠区龙福路二巷3号')],
        )

    def test_abbreviated_complete_middle_school_is_normalized(self):
        """完中应规范为完全中学。"""
        self.assertEqual(EXTRACTOR.normalize_school_type('完中'), '完全中学')

    def test_technical_schools_are_normalized_as_technical_colleges(self):
        """技师学院和技工学校应统一规范为技工院校。"""
        self.assertEqual(
            EXTRACTOR.normalize_school_type('技师学院'), '技工院校'
        )
        self.assertEqual(
            EXTRACTOR.normalize_school_type('技工学校'), '技工院校'
        )

    def test_chinese_name_line_break_space_is_removed(self):
        """中文校名因换行产生的内部空格应被移除。"""
        self.assertEqual(
            EXTRACTOR.normalize_place_name_text('广州市明珠高级中学有限 公司'),
            '广州市明珠高级中学有限公司',
        )

    def test_latin_name_space_is_preserved(self):
        """拉丁文字中的正常单词空格应继续保留。"""
        self.assertEqual(
            EXTRACTOR.normalize_place_name_text('Guangzhou Foreign School'),
            'Guangzhou Foreign School',
        )

    def test_inline_campuses_are_split_and_grade_notes_removed(self):
        """连续校区地址应拆行并移除年级说明。"""
        self.assertEqual(
            EXTRACTOR.split_explicit_campus_addresses(
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
            EXTRACTOR.split_explicit_campus_addresses(
                '示例学校', '广州市海珠区测试路1号'
            ),
            [('示例学校', '广州市海珠区测试路1号')],
        )

    def test_slash_separated_labeled_campuses_are_split(self):
        """斜杠分隔且各自带标签的校区地址应拆成多条。"""
        self.assertEqual(
            EXTRACTOR.split_explicit_campus_addresses(
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
            EXTRACTOR.split_explicit_campus_addresses(
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
            EXTRACTOR.split_explicit_campus_addresses(
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
            EXTRACTOR.deduplicate_school_records(school_records)
        )
        self.assertEqual(duplicate_count, 1)
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


if __name__ == '__main__':
    unittest.main()
