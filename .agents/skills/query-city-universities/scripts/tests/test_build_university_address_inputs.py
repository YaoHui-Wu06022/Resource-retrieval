"""高校页面结果聚合测试。"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_university_address_inputs import (
    build_output_payloads,
    build_page_results_payload,
    main,
)
from query_city_core.address.common import validate_address_record


def build_school(
    school_name='示例大学',
    school_identifier='4144010000',
    source_sequence='100',
):
    """构造一条高校基础记录。"""
    return {
        'source_sequence': source_sequence,
        'school_name': school_name,
        'school_identifier': school_identifier,
        'supervising_authority': '示例省教育厅',
        'location_city': '示例市',
        'education_level': '本科',
        'source_remark': '不应进入公共属性',
        'school_tag': '211',
        'school_nature': '公办',
    }


def build_page(url, candidates=None, hints=None):
    """构造一份页面提取结果。"""
    return {
        'stage': 'address_candidates',
        'requested_url': url,
        'final_url': url,
        'address_candidates': list(candidates or []),
        'campus_hints': list(hints or []),
        'related_links': [],
        'warnings': [],
    }


def build_completed_item(school, pages):
    """构造一条已完成学校结果。"""
    return {
        'school_identifier': school['school_identifier'],
        'processing_status': 'completed',
        'pages': pages,
    }


def build_skipped_item(
    school,
    reason='merged',
    reference='https://example.gov.cn/notice',
):
    """构造一条有证据的跳过学校结果。"""
    return {
        'school_identifier': school['school_identifier'],
        'processing_status': 'skipped',
        'skip_reason': reason,
        'skip_reference': reference,
    }


def build_payload(items):
    """构造精简高校检索结果。"""
    return {'items': items}


def build_city_context(city='示例市'):
    """构造高校批次使用的完整城市上下文。"""
    return {
        'stage': 'city_context',
        'input_city': city,
        'city_name': city,
        'province_name': None,
        'subdivisions': [],
    }


def build_city_universities_payload(schools, city='示例市'):
    """构造用于完整性核对的基础信息批次。"""
    return {
        'stage': 'city_universities',
        'city_context': build_city_context(city),
        'schools': schools,
    }


def build_address_payload(retrieval_payload, city_universities_payload):
    """构造测试断言使用的公共地址结果。"""
    return build_output_payloads(retrieval_payload, city_universities_payload)[1]


class BuildUniversityAddressRecordsTest(unittest.TestCase):
    def test_merges_pages_and_splits_address_and_hint_records(self):
        """多页结果应去重并拆成地址和兜底记录。"""
        school = build_school()
        page_one = build_page(
            'https://example.edu.cn/',
            candidates=[{
                'campus_hint': '东湖校区',
                'address_text': '示例市东湖区大学路1号',
            }],
            hints=['东湖校区', '滨海校区'],
        )
        page_two = build_page(
            'https://example.edu.cn/contact',
            candidates=[
                {
                    'campus_hint': '东湖校区',
                    'address_text': '示例市东湖区大学路1号',
                },
                {
                    'campus_hint': '',
                    'address_text': '示例市中心区学院路2号',
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page_one, page_two])]),
            build_city_universities_payload([school]),
        )

        self.assertEqual(
            [item['place_name'] for item in result['items']],
            ['示例大学东湖校区', '示例大学', '示例大学滨海校区'],
        )
        self.assertEqual(
            [item['original_address'] for item in result['items']],
            ['示例市东湖区大学路1号', '示例市中心区学院路2号', ''],
        )
        self.assertEqual(result['metrics']['page_count'], 2)
        self.assertEqual(result['metrics']['original_address_count'], 2)
        self.assertEqual(result['metrics']['missing_original_address_count'], 1)

    def test_binds_unlabeled_address_to_unique_cross_page_campus_token(self):
        school = build_school(school_name='广州美术学院')
        addresses = build_page(
            'https://example.edu.cn/',
            candidates=[
                {'campus_hint': '', 'address_text': '广州市海珠区昌岗东路257号'},
                {'campus_hint': '', 'address_text': '番禺区广州大学城外环西路168号'},
            ],
        )
        campuses = build_page(
            'https://example.edu.cn/about',
            hints=['昌岗校区', '大学城校区', '佛山校区'],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [addresses, campuses])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(
            [(item['attributes']['campus_name'], item['original_address'])
             for item in result['items']],
            [
                ('昌岗校区', '广州市海珠区昌岗东路257号'),
                ('大学城校区', '番禺区广州大学城外环西路168号'),
                ('佛山校区', ''),
            ],
        )

    def test_homepage_footer_campus_name_wins_over_location_alias(self):
        school = build_school(school_name='广州工商学院')
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '广州校区',
                    'address_text': '广州市花都区狮岭南环路28号',
                },
                {
                    'campus_hint': '佛山校区',
                    'address_text': '佛山市三水区乐平镇三花路166号',
                },
            ],
            hints=['广州校区', '佛山校区', '花都校区', '三水校区'],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(
            [item['attributes']['campus_name'] for item in result['items']],
            ['广州校区', '佛山校区'],
        )

    def test_removes_unlabeled_duplicate_of_campus_address(self):
        """已有校区地址时应删除同地址的无校区重复项。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '东湖校区',
                    'address_text': '示例市东湖区大学路1号',
                },
                {
                    'campus_hint': '',
                    'address_text': '示例市东湖区大学路1号',
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['place_name'], '示例大学东湖校区')

    def test_removes_unlabeled_variant_of_campus_address(self):
        """省份和街道前缀不同的同址无校区候选也应删除。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '校本部',
                    'address_text': '广东省示例市示例区小谷围街大学路1号',
                },
                {
                    'campus_hint': '',
                    'address_text': '示例市示例区大学路1号',
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['place_name'], '示例大学校本部')

    def test_keeps_unlabeled_address_with_different_detail(self):
        """道路或门牌不同的无校区候选不得被同址规则删除。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '校本部',
                    'address_text': '示例市示例区小谷围街大学路1号',
                },
                {
                    'campus_hint': '',
                    'address_text': '示例市示例区大学路2号',
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(len(result['items']), 2)

    def test_empty_page_result_builds_school_fallback(self):
        """无地址和校区时应生成学校名称兜底记录。"""
        school = build_school()
        result = build_address_payload(
            build_payload([
                build_completed_item(
                    school,
                    [build_page('https://example.edu.cn/')],
                )
            ]),
            build_city_universities_payload([school]),
        )
        item = result['items'][0]
        self.assertEqual(item['place_name'], '示例大学')
        self.assertEqual(item['original_address'], '')
        self.assertEqual(item['source_nature'], 'web_search')

    def test_full_school_name_in_campus_is_not_repeated(self):
        """校区名称含学校全名时不应重复拼接。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            hints=['示例大学滨海校区'],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(result['items'][0]['place_name'], '示例大学滨海校区')

    def test_school_attributes_match_city_universities_fields(self):
        """公共属性应保留基础信息字段并排除原始备注。"""
        school = build_school()
        result = build_address_payload(
            build_payload([
                build_completed_item(
                    school,
                    [build_page('https://example.edu.cn/')],
                )
            ]),
            build_city_universities_payload([school]),
        )
        attributes = result['items'][0]['attributes']
        self.assertEqual(attributes['school_identifier'], '4144010000')
        self.assertEqual(attributes['supervising_authority'], '示例省教育厅')
        self.assertEqual(attributes['school_tag'], '211')
        self.assertNotIn('source_remark', attributes)
        validate_address_record(result['items'][0])

    def test_rejects_more_than_six_pages(self):
        """超过校区详情扩展预算时应拒绝输入。"""
        school = build_school()
        pages = [
            build_page(f'https://example.edu.cn/page/{index}')
            for index in range(7)
        ]
        with self.assertRaisesRegex(ValueError, '页面数量超过6页预算'):
            build_address_payload(
                build_payload([build_completed_item(school, pages)]),
                build_city_universities_payload([school]),
            )

    def test_rejects_duplicate_school_results(self):
        """同一学校不得在批次中重复出现。"""
        school = build_school()
        item = build_completed_item(
            school,
            [build_page('https://example.edu.cn/')],
        )
        with self.assertRaisesRegex(ValueError, '学校结果重复'):
            build_address_payload(
                build_payload([item, item]),
                build_city_universities_payload([school]),
            )

    def test_warns_when_one_campus_has_multiple_addresses(self):
        """同一校区的不同地址应保留并生成警告。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '东湖校区',
                    'address_text': '示例市东湖区大学路1号',
                },
                {
                    'campus_hint': '东湖校区',
                    'address_text': '示例市东湖区大学路2号',
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['metrics']['warning_count'], 1)

    def test_skipped_school_counts_without_address_records(self):
        """有证据跳过的学校参与完整性核对但不生成地址记录。"""
        completed_school = build_school()
        skipped_school = build_school(
            school_name='已合并大学',
            school_identifier='4144010001',
            source_sequence='101',
        )
        result = build_address_payload(
            build_payload([
                build_completed_item(
                    completed_school,
                    [build_page('https://example.edu.cn/')],
                ),
                build_skipped_item(skipped_school),
            ]),
            build_city_universities_payload([completed_school, skipped_school]),
        )

        self.assertEqual(result['metrics']['city_university_count'], 2)
        self.assertEqual(result['metrics']['completed_school_count'], 1)
        self.assertEqual(result['metrics']['skipped_school_count'], 1)
        self.assertEqual(result['metrics']['missing_school_count'], 0)
        self.assertEqual(len(result['items']), 1)

    def test_rejects_missing_school_result(self):
        """基础名单中的学校缺少结果时应列出学校名称。"""
        completed_school = build_school()
        missing_school = build_school(
            school_name='遗漏大学',
            school_identifier='4144010001',
            source_sequence='101',
        )
        with self.assertRaisesRegex(ValueError, '缺少学校处理结果：遗漏大学'):
            build_address_payload(
                build_payload([
                    build_completed_item(
                        completed_school,
                        [build_page('https://example.edu.cn/')],
                    )
                ]),
                build_city_universities_payload([completed_school, missing_school]),
            )

    def test_rejects_old_item_without_processing_status(self):
        """旧格式没有处理状态时应拒绝输入。"""
        school = build_school()
        old_item = {
            'school_identifier': school['school_identifier'],
            'pages': [build_page('https://example.edu.cn/')],
        }
        with self.assertRaisesRegex(ValueError, 'processing_status'):
            build_address_payload(
                build_payload([old_item]),
                build_city_universities_payload([school]),
            )

    def test_rejects_skipped_school_without_valid_evidence(self):
        """跳过学校必须提供受限原因和可访问形式的证据URL。"""
        school = build_school()
        with self.subTest('原因无效'):
            with self.assertRaisesRegex(ValueError, 'skip_reason'):
                build_address_payload(
                    build_payload([
                        build_skipped_item(school, reason='other')
                    ]),
                    build_city_universities_payload([school]),
                )
        with self.subTest('证据URL无效'):
            with self.assertRaisesRegex(ValueError, '证据页面URL'):
                build_address_payload(
                    build_payload([
                        build_skipped_item(school, reference='搜索结果摘要')
                    ]),
                    build_city_universities_payload([school]),
                )

    def test_rejects_school_outside_city_universities(self):
        """页面结果不得包含城市高校名录外学校。"""
        city_university = build_school()
        unknown_school = build_school(
            school_name='未知大学',
            school_identifier='4144019999',
        )
        with self.assertRaisesRegex(ValueError, '城市高校名录外学校标识码：4144019999'):
            build_address_payload(
                build_payload([
                    build_completed_item(
                        unknown_school,
                        [build_page('https://unknown.edu.cn/')],
                    )
                ]),
                build_city_universities_payload([city_university]),
            )

    def test_rejects_old_full_school_object(self):
        """精简输入不得继续携带完整学校对象。"""
        school = build_school()
        old_item = {
            'school': school,
            'processing_status': 'completed',
            'pages': [build_page('https://example.edu.cn/')],
        }
        with self.assertRaisesRegex(ValueError, 'school_identifier'):
            build_address_payload(
                build_payload([old_item]),
                build_city_universities_payload([school]),
            )

    def test_builds_complete_page_results_from_city_universities(self):
        """脚本应补齐城市和完整学校对象并生成页面批次。"""
        school = build_school()
        retrieval_payload = build_payload([
            build_completed_item(
                school,
                [build_page('https://example.edu.cn/')],
            )
        ])
        result = build_page_results_payload(
            retrieval_payload,
            build_city_universities_payload([school]),
        )

        self.assertEqual(result['stage'], 'university_page_results')
        self.assertEqual(result['city_context'], build_city_context())
        self.assertEqual(result['items'][0]['school'], school)

    def test_rejects_old_complete_page_results_payload(self):
        """命令输入不再接受旧的完整页面批次格式。"""
        school = build_school()
        old_payload = {
            'stage': 'university_page_results',
            'city_context': build_city_context(),
            'items': [],
        }
        with self.assertRaisesRegex(ValueError, '仅包含 items'):
            build_address_payload(old_payload, build_city_universities_payload([school]))

    def test_main_reads_sibling_city_universities(self):
        """命令入口应读取基础信息并自动写出页面批次归档。"""
        school = build_school()
        page_payload = build_payload([
            build_completed_item(
                school,
                [build_page('https://example.edu.cn/')],
            )
        ])
        city_universities_payload = build_city_universities_payload([school])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / 'university_retrieval_results.json'
            base_path = root / 'city_universities.json'
            page_results_path = root / 'university_page_results.json'
            output_path = root / 'address_records.json'
            input_path.write_text(
                json.dumps(page_payload, ensure_ascii=False),
                encoding='utf-8',
            )
            base_path.write_text(
                json.dumps(city_universities_payload, ensure_ascii=False),
                encoding='utf-8',
            )
            arguments = [
                'build_university_address_inputs.py',
                '--input',
                str(input_path),
                '--output',
                str(output_path),
            ]
            with patch.object(sys, 'argv', arguments), redirect_stdout(io.StringIO()):
                main()
            output_payload = json.loads(output_path.read_text(encoding='utf-8'))
            page_results_payload = json.loads(
                page_results_path.read_text(encoding='utf-8')
            )

        self.assertEqual(output_payload['metrics']['city_university_count'], 1)
        self.assertEqual(output_payload['metrics']['missing_school_count'], 0)
        self.assertEqual(
            page_results_payload['city_context'], build_city_context()
        )
        self.assertEqual(page_results_payload['items'][0]['school'], school)


if __name__ == '__main__':
    unittest.main()
