#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试基础教育学校地址记录构造规则。"""

import sys
import tempfile
import unittest
import json
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import school_common as COMMON  # noqa: E402
import school_common as NORMALIZER  # noqa: E402
import school_government_flow as FLOW  # noqa: E402
import school_government_flow as INSPECTOR  # noqa: E402
from query_city_core.io_utils import write_json_payload  # noqa: E402


class SchoolSourceAndTypeFillTests(unittest.TestCase):
    """验证来源引用与跨校区类型补全规则。"""

    def test_unit_name_header_is_recognized(self):
        """官方“单位名称”表头应能被规则推断识别。"""
        rule = FLOW.infer_table_rule(
            [
                ['序号', '单位名称', '办学类型', '办学性质', '地址'],
                ['1', '示例学校', '小学', '公办', '示例路1号'],
            ],
            '名录.html',
            'table',
            {'table_index': 1},
        )
        self.assertIsNotNone(rule)
        self.assertIn(2, rule['place_name_columns'])

    def test_source_reference_is_not_wrapped_twice(self):
        """记录来源引用应直接使用引擎定位文本。"""
        record = COMMON.build_school_record(
            '示例学校',
            '示例路1号',
            '小学',
            '公办',
            {
                'content_url': 'https://example.gov/list',
                'publication_date': '2026-01-01',
            },
            'https://example.gov/list | 名录.html | row 2',
            '示例区',
        )
        self.assertEqual(
            record['source_reference'],
            'https://example.gov/list | 名录.html | row 2',
        )
        self.assertEqual(
            record['source_reference'].count('https://example.gov/list'),
            1,
        )

    def test_missing_campus_type_is_filled_from_unique_sibling(self):
        """同一学校基础名下的唯一非空类型应回填空类型校区。"""
        records = [
            {
                'place_name': '广州市海珠区华立学校（大沙校区）',
                'original_address': '海珠区南洲路1002号',
                'source_reference': 'https://example.gov/xls | row 1',
                'attributes': {
                    'administrative_unit': '海珠区',
                    'school_type': '九年一贯制',
                    'poi_name_aliases': [],
                },
            },
            {
                'place_name': '广州市海珠区华立学校（赤沙校区）',
                'original_address': '海珠区新滘镇赤沙村茶岗（坊里巷）院内',
                'source_reference': 'https://example.gov/xls | row 2',
                'attributes': {
                    'administrative_unit': '海珠区',
                    'school_type': '',
                    'poi_name_aliases': [],
                },
            },
        ]
        filled = NORMALIZER.fill_missing_school_type_from_siblings(records)
        self.assertEqual(
            filled[1]['attributes']['school_type'],
            '九年一贯制',
        )

    def test_cross_source_conflict_does_not_block_same_source_fill(self):
        """其他来源的不同类型不应阻止同来源内的唯一类型回填。"""
        records = [
            {
                'place_name': '华立学校（大沙校区）',
                'original_address': '海珠区南洲路1002号',
                'source_reference': 'https://example.gov/xls | row 1',
                'attributes': {
                    'administrative_unit': '海珠区',
                    'school_type': '九年一贯制',
                    'poi_name_aliases': [],
                },
            },
            {
                'place_name': '华立学校（赤沙校区）',
                'original_address': '海珠区新滘镇赤沙村茶岗（坊里巷）院内',
                'source_reference': 'https://example.gov/xls | row 2',
                'attributes': {
                    'administrative_unit': '海珠区',
                    'school_type': '',
                    'poi_name_aliases': [],
                },
            },
            {
                'place_name': '华立学校（赤沙校区）',
                'original_address': '海珠区新滘东路赤沙村茶园（坊望巷）院内',
                'source_reference': 'https://example.gov/jpg | row 3',
                'attributes': {
                    'administrative_unit': '海珠区',
                    'school_type': '初中',
                    'poi_name_aliases': [],
                },
            },
        ]
        filled = NORMALIZER.fill_missing_school_type_from_siblings(records)
        self.assertEqual(filled[1]['attributes']['school_type'], '九年一贯制')
        self.assertEqual(filled[2]['attributes']['school_type'], '初中')

    def test_missing_address_is_filled_from_unique_sibling(self):
        """同校区存在唯一官方地址时回填空地址记录。"""
        records = [
            {
                'place_name': '示例中学（逸景校区）',
                'original_address': '海珠区逸景路1号',
                'source_reference': 'https://a | row 1',
                'attributes': {
                    'administrative_unit': '海珠区',
                    'school_type': '初中',
                    'poi_name_aliases': [],
                },
            },
            {
                'place_name': '示例中学（逸景校区）',
                'original_address': '',
                'source_reference': 'https://b | row 2',
                'attributes': {
                    'administrative_unit': '海珠区',
                    'school_type': '初中',
                    'poi_name_aliases': [],
                },
            },
        ]
        filled = NORMALIZER.fill_missing_original_address_from_siblings(
            records
        )
        self.assertEqual(filled[1]['original_address'], '海珠区逸景路1号')

    def test_conflicting_sibling_types_do_not_fill_blank(self):
        """同一基础名下非空类型不唯一时不得推断。"""
        records = [
            {
                'place_name': '示例学校（东校区）',
                'original_address': '示例路1号',
                'attributes': {
                    'administrative_unit': '示例区',
                    'school_type': '小学',
                    'poi_name_aliases': [],
                },
            },
            {
                'place_name': '示例学校（西校区）',
                'original_address': '示例路2号',
                'attributes': {
                    'administrative_unit': '示例区',
                    'school_type': '完全中学',
                    'poi_name_aliases': [],
                },
            },
            {
                'place_name': '示例学校（南校区）',
                'original_address': '示例路3号',
                'attributes': {
                    'administrative_unit': '示例区',
                    'school_type': '',
                    'poi_name_aliases': [],
                },
            },
        ]
        filled = NORMALIZER.fill_missing_school_type_from_siblings(records)
        self.assertEqual(filled[2]['attributes']['school_type'], '')


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

    def test_merge_school_types_dedups_by_stage(self):
        """合并应保留官方类型标签并按覆盖学段去重。"""
        cases = {
            ('小学', '九年一贯制学校'): '九年一贯制学校',
            ('九年一贯制学校', '完全中学'): '九年一贯制学校、完全中学',
            ('完全中学', '初中'): '完全中学',
            ('十二年一贯制学校', '九年一贯制学校'): '十二年一贯制学校',
            ('十五年一贯制学校', '高中'): '十五年一贯制学校',
            ('完全中学', '小学'): '完全中学、小学',
            ('特殊教育学校', '小学'): '特殊教育学校、小学',
        }
        for (first_type, second_type), expected_type in cases.items():
            with self.subTest(first=first_type, second=second_type):
                self.assertEqual(
                    NORMALIZER.merge_school_types(first_type, second_type),
                    expected_type,
                )

    def test_parenthesized_specific_school_type_is_preserved(self):
        """括号内更具体的官方办学层次不得被外层粗分类覆盖。"""
        cases = {
            '▪ 学校类别：初中(九年一贯制学校)': '九年一贯制学校',
            '▪ 学校类别：初中(初级中学)': '初中',
            '▪ 学校类别：普通高中(完全中学)': '完全中学',
            '▪ 学校类别：普通高中(高级中学)': '高中',
            '▪ 学校类别：职业院校(中等职业学校)': '中等职业学校',
            '▪ 学校类别：小学': '小学',
        }
        for raw_type, expected_type in cases.items():
            with self.subTest(raw_type=raw_type):
                self.assertEqual(
                    NORMALIZER.normalize_school_type(raw_type), expected_type
                )

    def test_explicit_stage_campus_refines_school_type(self):
        """拆出的小学部、初中部和高中部记录应使用对应学段。"""
        for campus_name, expected_type in (
            ('示例学校小学部', '小学'),
            ('示例学校初中部', '初中'),
            ('示例学校高中部', '高中'),
        ):
            with self.subTest(campus_name=campus_name):
                record = COMMON.build_school_record(
                    campus_name,
                    '南山区测试路1号',
                    '完全中学',
                    '公办',
                    {},
                    '来源.html',
                    '南山区',
                )
                self.assertEqual(
                    record['attributes']['school_type'], expected_type
                )

    def test_name_marker_infers_year_consistent_school_type(self):
        """校名中的官方一贯制标记应推断为对应学校类型。"""
        cases = {
            '广州市示例学校（九年一贯制）': '九年一贯制学校',
            '广州市示例学校（十二年一贯制）': '十二年一贯制学校',
            '广州市示例学校（十五年一贯制）': '十五年一贯制学校',
        }
        for place_name, expected_type in cases.items():
            with self.subTest(place_name=place_name):
                self.assertEqual(
                    COMMON.infer_school_type_from_name_marker(place_name),
                    expected_type,
                )
                record = COMMON.build_school_record(
                    place_name,
                    '越秀区甲路1号',
                    '小学',
                    '公办',
                    {},
                    '来源.html',
                    '越秀区',
                )
                self.assertEqual(
                    record['attributes']['school_type'], expected_type
                )

    def test_absent_marker_keeps_source_school_type(self):
        """校名不含官方一贯制标记时保持来源提供的学校类型。"""
        record = COMMON.build_school_record(
            '广州市越秀区示例小学',
            '越秀区甲路1号',
            '小学',
            '公办',
            {},
            '来源.html',
            '越秀区',
        )
        self.assertEqual(record['attributes']['school_type'], '小学')

    def test_poi_name_aliases_are_generated_for_single_stage_records(self):
        """单学段记录生成同学段学部全名别名，多学段与校区名不生成。"""
        cases = {
            ('示例学校', '初中'): [
                '示例学校初中部',
                '示例学校中学部',
            ],
            ('示例学校', '小学'): ['示例学校小学部'],
            ('示例学校（中学部）', '初中'): [
                '示例学校',
                '示例学校初中部',
            ],
            ('示例学校', '完全中学'): [],
            ('示例学校（起义路校区）', '初中'): [],
        }
        for (place_name, school_type), expected_aliases in cases.items():
            with self.subTest(place_name=place_name, school_type=school_type):
                self.assertEqual(
                    NORMALIZER.build_poi_name_aliases(
                        place_name,
                        school_type,
                    ),
                    expected_aliases,
                )

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

    def test_slash_campuses_split_when_one_segment_is_unparsable(self):
        """斜杠校区中部分段无法识别时，已识别段照常拆开并保留其余段。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '广州市天河区龙口西小学',
                '天河区龙口西路63号（龙口校区）/'
                '天河区龙口东路401号（穗园校区）/'
                '天河区龙口中路87号（瑞安校区）/'
                '天河区龙口中路6号（帝景校区 借）',
            ),
            [
                ('广州市天河区龙口西小学龙口校区', '天河区龙口西路63号'),
                ('广州市天河区龙口西小学穗园校区', '天河区龙口东路401号'),
                ('广州市天河区龙口西小学瑞安校区', '天河区龙口中路87号'),
                (
                    '广州市天河区龙口西小学',
                    '天河区龙口中路6号（帝景校区 借）',
                ),
            ],
        )

    def test_slash_address_without_campus_labels_is_unchanged(self):
        """不含校区标签的斜杠地址不得按斜杠拆分。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例学校', '天河区龙口西路/天河东路之间'
            ),
            [('示例学校', '天河区龙口西路/天河东路之间')],
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

    def test_delimited_prefix_campuses_drop_separator_punctuation(self):
        """分号分隔的前置校区标签不应把分隔符带入名称或地址。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例学校',
                '南山校区：南山区甲路1号；福田校区：福田区乙路2号。',
            ),
            [
                ('示例学校南山校区', '南山区甲路1号'),
                ('示例学校福田校区', '福田区乙路2号'),
            ],
        )

    def test_nested_prefix_and_parenthesized_campuses_are_split(self):
        """学部校区地址内仍含括号校区标签时应逐级拆分为独立记录。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '广州市知用学校（九年一贯制）',
                '中学部校区：广州市百灵路83号'
                '小学部校区：（净慧校区）广州市越秀区净慧路39号'
                '（光孝校区）广州市越秀区净慧路90号'
                '（祝寿校区）广州市越秀区海珠北路祝寿巷11号',
            ),
            [
                (
                    '广州市知用学校（九年一贯制）中学部校区',
                    '广州市百灵路83号',
                ),
                (
                    '广州市知用学校（九年一贯制）小学部校区净慧校区',
                    '广州市越秀区净慧路39号',
                ),
                (
                    '广州市知用学校（九年一贯制）小学部校区光孝校区',
                    '广州市越秀区净慧路90号',
                ),
                (
                    '广州市知用学校（九年一贯制）小学部校区祝寿校区',
                    '广州市越秀区海珠北路祝寿巷11号',
                ),
            ],
        )

    def test_prefix_campus_chain_without_separator_is_split(self):
        """连续校区前缀标签应拆开且不被长标签吞并。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '广州市八一实验学校（九年一贯制）',
                '南校区：广州市越秀区达道路'
                '北校区：广州市越秀区共和路8巷24号共和苑内',
            ),
            [
                (
                    '广州市八一实验学校（九年一贯制）南校区',
                    '广州市越秀区达道路',
                ),
                (
                    '广州市八一实验学校（九年一贯制）北校区',
                    '广州市越秀区共和路8巷24号共和苑内',
                ),
            ],
        )

    def test_ben_jia_and_ben_xiao_campus_prefixes_are_split(self):
        """本校/分校与南/北校区地址标签应正确拆开。"""
        cases = [
            (
                '广州市越秀区朝天小学',
                '本校：广州市越秀区朝天路81号 '
                '分校：广州市越秀区光孝路陶家巷9-11号',
                [
                    ('广州市越秀区朝天小学本校', '广州市越秀区朝天路81号'),
                    (
                        '广州市越秀区朝天小学分校',
                        '广州市越秀区光孝路陶家巷9-11号',
                    ),
                ],
            ),
            (
                '广州市越秀区秉正小学',
                '南校区地址：广州市越秀区德政中路担杆巷21号'
                '北校区地址：广州市越秀区中山四路秉政街42号',
                [
                    (
                        '广州市越秀区秉正小学南校区',
                        '广州市越秀区德政中路担杆巷21号',
                    ),
                    (
                        '广州市越秀区秉正小学北校区',
                        '广州市越秀区中山四路秉政街42号',
                    ),
                ],
            ),
        ]
        for place_name, original_address, expected in cases:
            with self.subTest(place_name=place_name):
                self.assertEqual(
                    NORMALIZER.split_explicit_campus_addresses(
                        place_name, original_address
                    ),
                    expected,
                )

    def test_dash_separated_directional_campuses_are_split(self):
        """破折号分隔的东/西校区地址应拆为独立记录。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '广州市越秀区红火炬小学',
                '东校区—东华西路海月东街93号'
                '西校区—东华西路永安横街24号',
            ),
            [
                (
                    '广州市越秀区红火炬小学东校区',
                    '东华西路海月东街93号',
                ),
                (
                    '广州市越秀区红火炬小学西校区',
                    '东华西路永安横街24号',
                ),
            ],
        )

    def test_multi_branch_campus_chain_is_split(self):
        """正校与多个分校连写时应逐段拆开。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '广州市越秀区海珠中路小学',
                '海珠中正校：广州市海珠中路15号'
                '纸行分校：广州市纸行路34号'
                '七株榕分校：广州市海珠中路七株榕街9号'
                '天成分校：广州市天成路濠畔街370号',
            ),
            [
                (
                    '广州市越秀区海珠中路小学海珠中正校',
                    '广州市海珠中路15号',
                ),
                (
                    '广州市越秀区海珠中路小学纸行分校',
                    '广州市纸行路34号',
                ),
                (
                    '广州市越秀区海珠中路小学七株榕分校',
                    '广州市海珠中路七株榕街9号',
                ),
                (
                    '广州市越秀区海珠中路小学天成分校',
                    '广州市天成路濠畔街370号',
                ),
            ],
        )

    def test_zheng_xiao_parenthesized_prefix_is_split(self):
        """括号前缀中的正校标签应作为独立校区拆开。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '广州市越秀区广中路小学',
                '（广中校区）越秀区广中路22号'
                '（广中正校）越秀区正南路锦荣街23号'
                '（越华校区）越秀区越华路小东营3号之一',
            ),
            [
                (
                    '广州市越秀区广中路小学广中校区',
                    '越秀区广中路22号',
                ),
                (
                    '广州市越秀区广中路小学广中正校',
                    '越秀区正南路锦荣街23号',
                ),
                (
                    '广州市越秀区广中路小学越华校区',
                    '越秀区越华路小东营3号之一',
                ),
            ],
        )

    def test_unresolved_campus_boundary_marks_ambiguity(self):
        """校区边界无法唯一确定时应保留原文并标记待复核。"""
        original_address = '广州市越秀区甲路1号（东校区）乙路2号'
        records = COMMON.build_records_for_locations(
            '示例学校',
            original_address,
            '小学',
            '公办',
            {},
            '来源.html | row 2',
            '越秀区',
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['original_address'], original_address)
        self.assertIn(
            '校区边界无法确定', records[0]['attributes']['address_ambiguity']
        )

    def test_degenerate_nested_labels_do_not_split_or_loop(self):
        """相邻嵌套标签无实际地址时不拆分且不得进入死循环。"""
        original_address = (
            '总校区：南校区：天河区甲路1号'
        )
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例学校',
                original_address,
            ),
            [('示例学校', original_address)],
        )

    def test_parenthesized_suffix_stage_addresses_are_split(self):
        """地址末尾标注的中学部和小学部应拆为独立学段记录。"""
        self.assertEqual(
            NORMALIZER.split_explicit_campus_addresses(
                '示例学校',
                '南山区甲路1号（中学部）；南山区乙路2号（小学部）',
            ),
            [
                ('示例学校中学部', '南山区甲路1号'),
                ('示例学校小学部', '南山区乙路2号'),
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
            COMMON.classify_school_type_from_presence(
                ['1', '示例学校', '5', '220', '6', '280'], column_mappings
            ),
            '小学、初中',
        )

    def test_source_publication_date_is_preserved(self):
        """来源发布日期应保留，缺失时应使用当天日期。"""
        dated_record = COMMON.build_school_record(
            '示例小学', '荔湾区甲路1号', '小学', '公办',
            {'publication_date': '2026-08-01'}, '来源.html | row 1', '荔湾区'
        )
        blank_record = COMMON.build_school_record(
            '示例中学', '荔湾区乙路2号', '初中', '公办',
            {}, '来源.html | row 2', '荔湾区'
        )
        self.assertEqual(
            dated_record['attributes']['publication_date'], '2026-08-01'
        )
        self.assertEqual(
            blank_record['attributes']['publication_date'], date.today().isoformat()
        )

    def test_key_value_rule_applies_to_multiple_declared_html_files(self):
        """一条文件模式规则应提取多个同构政府详情页并保留各自网址。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            detail_dir = source_dir / '幼儿园详情'
            detail_dir.mkdir()
            files = []
            for index in (1, 2):
                relative_name = f'幼儿园详情/详情{index}.html'
                (source_dir / relative_name).write_text(
                    '<table><tr><td>幼儿园名称</td>'
                    f'<td>示例幼儿园{index}</td></tr>'
                    '<tr><td>地址</td>'
                    f'<td>南山区测试路{index}号</td></tr>'
                    '<tr><td>办园性质</td><td>公办幼儿园</td></tr></table>',
                    encoding='utf-8',
                )
                files.append({
                    'file': relative_name,
                    'source_url': f'https://example.gov/detail/{index}',
                })
            write_json_payload(
                source_dir / 'government_source.json',
                {},
            )
            plan = {
                'stage': 'basic_education_extraction_plan',
                'city_context': {
                    'stage': 'city_context',
                    'input_city': '广州',
                    'city_name': '广州市',
                    'province_name': '广东省',
                    'subdivisions': [{
                        'name': '越秀区',
                        'adcode': '440104',
                        'level': 'district',
                    }],
                },
                'administrative_unit': {
                    'name': '越秀区',
                    'adcode': '440104',
                    'level': 'district',
                },
                'government_source_file': 'government_source.json',
                'items': [{
                    'source_title': '幼儿园详情',
                    'publisher': '越秀区教育局',
                    'publication_date': '2026-08-01',
                    'landing_page_url': 'https://example.gov/list',
                    'content_url': 'https://example.gov/list',
                    'covered_school_types': ['幼儿园'],
                    'contains_address': True,
                    'files': files,
                    'extraction_rules': [{
                        'file_pattern': '幼儿园详情/*.html',
                        'kind': 'html_key_value',
                        'attribute_fields': [
                            {'field': 'school_type', 'value': '幼儿园'},
                        ],
                        'approved': True,
                    }],
                    'review_status': 'ready',
                }],
            }
            plan_path = source_dir / 'extraction_plan.json'
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False), encoding='utf-8'
            )
            payload, exit_code = FLOW.extract_school_records(plan_path)
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload['metrics']['item_count'], 2)
        self.assertEqual(payload['metrics']['original_address_count'], 2)
        self.assertIn(
            'https://example.gov/detail/1',
            payload['items'][0]['source_reference'],
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
            'coverage_notes': {
                school_type: (
                    '高中按市级优先核验市招考机构与数据平台后'
                    '仍未检索到可用政府名录'
                    if school_type == '高中'
                    else '按区级优先核验并回退市级后'
                    '仍未检索到可用政府名录'
                )
                for school_type in ('幼儿园', '小学', '初中', '高中')
            },
            'items': [],
        }

    def build_completed_source_manifest_for_details(self, files):
        """返回包含同构详情页的完整来源清单。"""
        manifest = self.build_source_manifest()
        manifest['processing_status'] = 'completed'
        manifest['school_type_coverage'] = {
            school_type: 'covered'
            for school_type in ('幼儿园', '小学', '初中', '高中')
        }
        manifest['items'] = [{
            'source_title': '幼儿园详情',
            'publisher': '越秀区教育局',
            'publication_date': '2026-08-01',
            'landing_page_url': 'https://example.gov/list',
            'content_url': 'https://example.gov/list',
            'covered_school_types': ['幼儿园'],
            'contains_address': True,
            'local_files': [file['file'] for file in files],
            'local_file_urls': {
                file['file']: file['source_url'] for file in files
            },
        }]
        return manifest

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

    def test_source_item_accepts_urls_for_downloaded_detail_files(self):
        """同一来源的详情页应能逐文件记录实际政府网址。"""
        source_manifest = self.build_completed_source_manifest_for_details([
            {
                'file': '幼儿园详情/详情1.html',
                'source_url': 'https://www.example.gov.cn/detail/1',
            }
        ])
        _, _, items = INSPECTOR.validate_source_manifest(source_manifest)
        self.assertEqual(
            items[0]['local_file_urls']['幼儿园详情/详情1.html'],
            'https://www.example.gov.cn/detail/1',
        )

    def test_source_item_accepts_no_text_alternative_reason(self):
        """无文本替代的图片来源应能登记 source_form_reason。"""
        source_manifest = self.build_source_manifest()
        source_manifest['processing_status'] = 'partial'
        source_manifest['school_type_coverage']['小学'] = 'covered'
        source_manifest['items'] = [{
            'source_title': '小学名录（扫描版）',
            'publisher': '越秀区教育局',
            'publication_date': '2026-08-01',
            'landing_page_url': 'https://www.example.gov.cn/notice/1',
            'content_url': 'https://www.example.gov.cn/files/list.png',
            'covered_school_types': ['小学'],
            'contains_address': True,
            'local_files': ['小学名录.png'],
            'source_form_reason': 'no_text_alternative',
        }]
        _, _, items = INSPECTOR.validate_source_manifest(source_manifest)
        self.assertEqual(
            items[0]['source_form_reason'], 'no_text_alternative'
        )

    def test_source_item_rejects_invalid_source_form_reason(self):
        """source_form_reason 只接受 no_text_alternative。"""
        source_manifest = self.build_source_manifest()
        source_manifest['processing_status'] = 'partial'
        source_manifest['school_type_coverage']['小学'] = 'covered'
        source_manifest['items'] = [{
            'source_title': '小学名录（扫描版）',
            'publisher': '越秀区教育局',
            'publication_date': '2026-08-01',
            'landing_page_url': 'https://www.example.gov.cn/notice/1',
            'content_url': 'https://www.example.gov.cn/files/list.png',
            'covered_school_types': ['小学'],
            'contains_address': True,
            'local_files': ['小学名录.png'],
            'source_form_reason': 'vision_ocr',
        }]
        with self.assertRaisesRegex(ValueError, 'source_form_reason'):
            INSPECTOR.validate_source_manifest(source_manifest)

    def test_non_covered_school_type_requires_coverage_note(self):
        """非 covered 学段必须在 coverage_notes 中说明检索层级与结论。"""
        source_manifest = self.build_source_manifest()
        del source_manifest['coverage_notes']['高中']
        with self.assertRaisesRegex(ValueError, 'coverage_notes'):
            INSPECTOR.validate_source_manifest(source_manifest)

    def test_coverage_notes_require_non_empty_string_values(self):
        """coverage_notes 的学段说明必须是非空字符串。"""
        for invalid_note in ('', 2026, None):
            with self.subTest(value=invalid_note):
                source_manifest = self.build_source_manifest()
                source_manifest['coverage_notes']['高中'] = invalid_note
                with self.assertRaisesRegex(
                    ValueError, 'coverage_notes'
                ):
                    INSPECTOR.validate_source_manifest(source_manifest)

    def test_full_coverage_does_not_require_coverage_notes(self):
        """四类均为 covered 时 coverage_notes 为可选字段。"""
        source_manifest = self.build_source_manifest()
        source_manifest['processing_status'] = 'completed'
        source_manifest['school_type_coverage'] = {
            school_type: 'covered'
            for school_type in ('幼儿园', '小学', '初中', '高中')
        }
        source_manifest['items'] = [{
            'source_title': '全区学校名录',
            'publisher': '越秀区教育局',
            'publication_date': '2026-08-01',
            'landing_page_url': 'https://www.example.gov.cn/notice/1',
            'content_url': 'https://www.example.gov.cn/files/list.xlsx',
            'covered_school_types': ['幼儿园', '小学', '初中', '高中'],
            'contains_address': True,
            'local_files': ['全区学校名录.xlsx'],
        }]
        del source_manifest['coverage_notes']
        _, _, items = INSPECTOR.validate_source_manifest(source_manifest)
        self.assertEqual(items, source_manifest['items'])

    def test_inspect_consolidates_identical_key_value_detail_pages(self):
        """inspect 应把同目录同结构详情页合并为一条文件模式规则。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            detail_dir = source_dir / '幼儿园详情'
            detail_dir.mkdir()
            files = []
            for index in (1, 2):
                relative_name = f'幼儿园详情/详情{index}.html'
                (source_dir / relative_name).write_text(
                    '<table><tr><td>幼儿园名称</td>'
                    f'<td>示例幼儿园{index}</td></tr>'
                    '<tr><td>地址</td>'
                    f'<td>越秀区测试路{index}号</td></tr>'
                    '<tr><td>办园性质</td><td>公办幼儿园</td></tr></table>',
                    encoding='utf-8',
                )
                files.append({
                    'file': relative_name,
                    'source_url': f'https://www.example.gov.cn/detail/{index}',
                })
            input_path = source_dir / 'government_source.json'
            write_json_payload(
                input_path,
                self.build_completed_source_manifest_for_details(files),
            )
            plan, exit_code = INSPECTOR.build_extraction_plan(
                input_path, source_dir / 'extraction_plan.json'
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            plan['items'][0]['extraction_rules'][0]['file_pattern'],
            '幼儿园详情/*.html',
        )
        self.assertEqual(len(plan['items'][0]['extraction_rules']), 1)
        self.assertEqual(
            plan['items'][0]['files'][0]['source_url'],
            'https://www.example.gov.cn/detail/1',
        )

    def test_repeated_school_cards_do_not_treat_metadata_as_name(self):
        """学校类别容器含“学校”二字时仍应选择标题作为校名。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / '学校目录.html'
            source_path.write_text(
                ''.join(
                    '<div class="text">'
                    f'<h3><a>示例学校{index}</a></h3>'
                    f'<p>南山区测试路{index}号</p>'
                    '<div class="bottom"><ul>'
                    '<li>学校类别：普通高中(高级中学)</li>'
                    '<li>学校性质：公办</li>'
                    '</ul></div></div>'
                    for index in range(1, 4)
                ),
                encoding='utf-8',
            )
            _, rules, _ = INSPECTOR.collect_repeated_html_candidates(
                source_path, source_path.name
            )
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['row_selector'], 'div.text')
        self.assertEqual(
            rules[0]['place_name_selector'], ':scope > :nth-child(1)'
        )
        self.assertEqual(
            rules[0]['original_address_selector'], ':scope > :nth-child(2)'
        )
        attribute_fields = {
            item['field']: item
            for item in rules[0]['attribute_fields']
        }
        self.assertIn(
            '学校类别',
            attribute_fields['school_type']['selector'],
        )
        self.assertIn(
            '学校性质',
            attribute_fields['school_nature']['selector'],
        )

    def test_build_extraction_plan_preserves_city_scope(self):
        """inspect 输出应继续原样传递城市上下文和行政单位。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            input_path = source_dir / 'government_source.json'
            output_path = source_dir / 'extraction_plan.json'
            write_json_payload(
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


class InspectionRuleSuggestionTests(unittest.TestCase):
    """验证 inspect 对学校类型与向下填充列的自动建议。"""

    def setUp(self):
        """构造包含越秀区的城市上下文。"""
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

    def build_single_type_manifest(self, file_name):
        """返回只覆盖幼儿园一类来源的清单。"""
        return {
            'stage': 'basic_education_government_source',
            'city_context': self.city_context,
            'administrative_unit': self.administrative_unit,
            'processing_status': 'partial',
            'school_type_coverage': {
                '幼儿园': 'covered',
                '小学': 'no_official_source',
                '初中': 'no_official_source',
                '高中': 'no_official_source',
            },
            'coverage_notes': {
                school_type: (
                    '高中按市级优先核验市招考机构与数据平台后'
                    '仍未检索到可用政府名录'
                    if school_type == '高中'
                    else '按区级优先核验并回退市级后'
                    '仍未检索到可用政府名录'
                )
                for school_type in ('小学', '初中', '高中')
            },
            'items': [{
                'source_title': '越秀区幼儿园基本情况',
                'publisher': '越秀区教育局',
                'publication_date': '2026-08-01',
                'landing_page_url': 'https://www.example.gov.cn/yey',
                'content_url': 'https://www.example.gov.cn/yey',
                'covered_school_types': ['幼儿园'],
                'contains_address': True,
                'local_files': [file_name],
                'local_file_urls': {
                    file_name: 'https://www.example.gov.cn/yey',
                },
            }],
        }

    def test_single_covered_type_prefills_school_type_value(self):
        """单一覆盖类型且无类型列时，inspect 应预填固定学校类型。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            file_name = '幼儿园名录.html'
            (source_dir / file_name).write_text(
                '<table><tr><td>2022年名录表</td></tr>'
                '<tr><th>学校性质</th><th>学校名称</th>'
                '<th>所在街道</th><th>具体地址</th>'
                '<th>联系电话</th></tr>'
                '<tr><td>区属公办</td><td>示例幼儿园</td>'
                '<td>梅花村街道</td><td>越秀区甲路1号</td>'
                '<td>020-12345678</td></tr></table>',
                encoding='utf-8',
            )
            input_path = source_dir / 'government_source.json'
            write_json_payload(
                input_path, self.build_single_type_manifest(file_name)
            )
            plan, exit_code = INSPECTOR.build_extraction_plan(
                input_path, source_dir / 'extraction_plan.json'
            )
        self.assertEqual(exit_code, 0)
        extraction_rule = plan['items'][0]['extraction_rules'][0]
        school_type_entry = next(
            item for item in extraction_rule['attribute_fields']
            if item['field'] == 'school_type'
        )
        self.assertEqual(school_type_entry['value'], '幼儿园')
        self.assertFalse(extraction_rule['approved'])

    def test_empty_nature_cells_suggest_fill_down_column(self):
        """办学性质列存在空单元格时应建议加入向下填充列。"""
        table_rows = [
            ['学校性质', '学校名称', '所在街道', '具体地址', '联系电话'],
            ['区属公办', '示例小学', '梅花村街道', '越秀区甲路1号', '电话'],
            ['', '示例小学分部', '梅花村街道', '越秀区乙路2号', '电话'],
        ]
        extraction_rule = INSPECTOR.infer_table_rule(
            table_rows,
            '名录.pdf',
            'pdf_table',
            {'page': 1, 'table_index': 1},
        )
        self.assertIn(1, extraction_rule['fill_down_columns'])
        school_nature_entry = next(
            item for item in extraction_rule['attribute_fields']
            if item['field'] == 'school_nature'
        )
        self.assertEqual(school_nature_entry['column'], 1)


class PreviewExtractionPlanTests(unittest.TestCase):
    """验证提取计划的行覆盖与重叠复核。"""

    def build_table_rule(self, file_name, exclude_rows, school_type='小学'):
        """构造已批准的表格提取规则。"""
        return {
            'file': file_name,
            'kind': 'table',
            'location': {'table_index': 1},
            'header_row': 1,
            'data_start_row': 2,
            'data_end_row': None,
            'place_name_columns': [1],
            'place_name_separator': '',
            'original_address_column': 2,
            'attribute_fields': [
                {
                    'field': 'school_type',
                    'column': None,
                    'value': school_type,
                    'selector': '',
                    'labels': [],
                },
                {
                    'field': 'school_nature',
                    'column': None,
                    'value': '公办',
                    'selector': '',
                    'labels': [],
                },
            ],
            'fill_down_columns': [],
            'required_cell_values': [],
            'exclude_rows': exclude_rows,
            'approved': True,
        }

    def write_preview_plan(self, source_dir, extraction_rules):
        """写入供复核的最小提取计划与来源表格。"""
        file_name = '名录.html'
        (source_dir / file_name).write_text(
            '<table><thead><tr><th>名称</th><th>地址</th></tr></thead>'
            '<tbody><tr><td>示例小学一</td><td>甲路1号</td></tr>'
            '<tr><td>示例小学二</td><td>乙路2号</td></tr>'
            '<tr><td>示例小学三</td><td>丙路3号</td></tr></tbody></table>',
            encoding='utf-8',
        )
        plan_path = source_dir / 'extraction_plan.json'
        write_json_payload(plan_path, {
            'stage': 'basic_education_extraction_plan',
            'items': [{
                'local_files': [file_name],
                'derived_files': [],
                'extraction_rules': extraction_rules,
            }],
        })
        return plan_path

    def test_preview_reports_complete_coverage(self):
        """全部数据行都被规则覆盖时复核通过。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            plan_path = self.write_preview_plan(
                source_dir,
                [self.build_table_rule('名录.html', [])],
            )
            preview_payload, exit_code = FLOW.preview_extraction_plan(
                plan_path
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(preview_payload['candidate_row_count'], 3)
        self.assertEqual(preview_payload['covered_row_count'], 3)
        self.assertEqual(preview_payload['uncovered_row_count'], 0)
        self.assertEqual(preview_payload['overlap_row_count'], 0)
        self.assertEqual(preview_payload['type_counts'], {'小学': 3})

    def test_preview_reports_overlapping_rows(self):
        """多条规则重复命中同一行时复核不通过。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            first_rule = self.build_table_rule(
                '名录.html', [3, 4], school_type='小学'
            )
            second_rule = self.build_table_rule(
                '名录.html', [], school_type='初中'
            )
            plan_path = self.write_preview_plan(
                source_dir, [first_rule, second_rule]
            )
            preview_payload, exit_code = FLOW.preview_extraction_plan(
                plan_path
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(preview_payload['uncovered_row_count'], 0)
        self.assertEqual(
            preview_payload['files'][0]['overlap_rows'], [2]
        )

    def test_preview_reports_uncovered_rows(self):
        """存在未被任何规则覆盖的数据行时复核不通过。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            plan_path = self.write_preview_plan(
                source_dir,
                [self.build_table_rule('名录.html', [3, 4])],
            )
            preview_payload, exit_code = FLOW.preview_extraction_plan(
                plan_path
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            preview_payload['files'][0]['uncovered_rows'], [3, 4]
        )
        self.assertEqual(preview_payload['covered_row_count'], 1)


if __name__ == '__main__':
    unittest.main()
