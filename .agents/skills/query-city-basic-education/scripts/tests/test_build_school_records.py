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

import extract_school_records as EXTRACTOR  # noqa: E402
import inspect_government_source as INSPECTOR  # noqa: E402
import normalize_school_records as NORMALIZER  # noqa: E402
from query_city_core.io_utils import write_json_payload  # noqa: E402


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
                record = EXTRACTOR.build_school_record(
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

    def test_html_css_records_split_explicit_stage_addresses(self):
        """政府目录网页中的多学段地址应拆为独立记录。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / '学校目录.html'
            source_path.write_text(
                '<div id="dataList"><div class="cont">'
                '<div class="text"><h3><a>示例学校</a></h3>'
                '<p>初中部：南山区甲路1号；高中部：南山区乙路2号</p>'
                '</div><div class="bottom"><ul>'
                '<li>学校类别：普通高中(完全中学)</li>'
                '<li>学校性质：公办</li></ul></div></div></div>',
                encoding='utf-8',
            )
            records = EXTRACTOR.extract_html_css_records(
                source_path,
                {
                    'row_selector': '#dataList > div.cont',
                    'place_name_selector': '.text > h3 > a',
                    'original_address_selector': '.text > p',
                    'school_type_selector': '.bottom li:nth-child(1)',
                    'school_nature_selector': '.bottom li:nth-child(2)',
                },
                {},
                '南山区',
            )
        self.assertEqual(
            [(record['place_name'], record['attributes']['school_type'])
             for record in records],
            [('示例学校初中部', '初中'), ('示例学校高中部', '高中')],
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
                        'school_type_value': '幼儿园',
                        'approved': True,
                    }],
                    'review_status': 'ready',
                }],
            }
            plan_path = source_dir / 'extraction_plan.json'
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False), encoding='utf-8'
            )
            payload, exit_code = EXTRACTOR.extract_school_records(plan_path)
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
        self.assertIn('学校类别', rules[0]['school_type_selector'])
        self.assertIn('学校性质', rules[0]['school_nature_selector'])

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
        self.assertEqual(extraction_rule['school_type_value'], '幼儿园')
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
        self.assertEqual(extraction_rule['school_nature_column'], 1)


if __name__ == '__main__':
    unittest.main()
