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

from build_university_address import (
    build_output_payloads,
    build_page_results_payload,
    clean_school_address_records,
    main,
    postprocess_university_address_records,
)
from university_campus_rules import clean_address_text, has_contact_label_noise
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
        'school_tag': '211',
        'school_nature': '公办',
    }


def build_map_record(school_identifier, campus_name, map_address):
    """构造一条含地图地址和校区属性的记录。"""
    return {
        'map_address': map_address,
        'attributes': {
            'school_identifier': school_identifier,
            'campus_name': campus_name,
        },
    }


def build_page(
    url,
    candidates=None,
    hints=None,
    related_links=None,
    title='',
):
    """构造一份页面提取结果。"""
    return {
        'stage': 'address_candidates',
        'requested_url': url,
        'final_url': url,
        'title': title,
        'address_candidates': list(candidates or []),
        'campus_hints': list(hints or []),
        'related_links': list(related_links or []),
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


def build_no_official_site_item(
    school,
    evidence_url='https://example.gov.cn/official-record',
    reason='2026 年新设，未找到归属明确的独立官网',
):
    """构造一条无官网学校结果。"""
    return {
        'school_identifier': school['school_identifier'],
        'processing_status': 'no_official_site',
        'evidence_url': evidence_url,
        'reason': reason,
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
    def test_no_official_site_generates_empty_address_record(self):
        """无官网学校生成空地址记录并保留证据与异常原因。"""
        school = build_school()
        item = build_no_official_site_item(school)
        retrieval_payload = build_payload([item])
        city_payload = build_city_universities_payload([school])

        result = build_address_payload(
            retrieval_payload,
            city_payload,
        )

        self.assertEqual(result['metrics']['no_official_site_school_count'], 1)
        self.assertEqual(result['metrics']['item_count'], 1)
        record = result['items'][0]
        self.assertEqual(record['place_name'], school['school_name'])
        self.assertEqual(record['original_address'], '')
        self.assertEqual(
            record['source_reference'],
            'https://example.gov.cn/official-record',
        )
        self.assertEqual(
            record['attributes']['abnormal_reason'],
            '2026 年新设，未找到归属明确的独立官网',
        )

    def test_no_official_site_requires_fields(self):
        """无官网结果缺少证据 URL 时被拒绝。"""
        school = build_school()
        item = {
            'school_identifier': school['school_identifier'],
            'processing_status': 'no_official_site',
            'evidence_url': '',
            'reason': '无官网',
        }
        retrieval_payload = build_payload([item])
        city_payload = build_city_universities_payload([school])

        with self.assertRaisesRegex(ValueError, '无官网时必须提供证据页面 URL'):
            build_output_payloads(retrieval_payload, city_payload)

    def test_merges_pages_and_splits_address_and_hint_records(self):
        """多页结果去重后，与校区不同址的无标签非主页地址按噪音丢弃。"""
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
            ['示例大学东湖校区', '示例大学滨海校区'],
        )
        self.assertEqual(
            [item['original_address'] for item in result['items']],
            ['示例市东湖区大学路1号', ''],
        )
        self.assertEqual(result['metrics']['page_count'], 2)
        self.assertEqual(result['metrics']['original_address_count'], 1)
        self.assertEqual(result['metrics']['missing_original_address_count'], 1)

    def test_fee_candidate_does_not_create_duplicate_address_row(self):
        """同校区费用行不再与真实地址并列成第二条记录。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '东湖校区',
                    'address_text': '示例市东湖区大学路166号',
                },
                {
                    'campus_hint': '东湖校区',
                    'address_text': (
                        '1600元/生·学年；清远校区：3000元/生·学年'
                    ),
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(
            result['items'][0]['original_address'],
            '示例市东湖区大学路166号',
        )
        self.assertEqual(result['warnings'], [])

    def test_direction_and_narrative_candidates_do_not_create_rows(self):
        """方向距离与职责叙述候选不产生假行。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '',
                    'address_text': '广州市天河区迎福路527号',
                },
                {
                    'campus_hint': '广州校区',
                    'address_text': '广州市增城区增城职教园东行4千米',
                },
                {
                    'campus_hint': '主校区',
                    'address_text': (
                        '嘉禾校区，主要承担全日制本科生教育任务；'
                        '滨江校区主要承担民警培训和成人教育任务'
                    ),
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(
            result['items'][0]['original_address'],
            '广州市天河区迎福路527号',
        )

    def test_institution_only_candidate_does_not_create_fake_campus(self):
        """招生章程页里的合作学校校区名（整串机构名）不再产生假记录。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/zhaosheng.htm',
            candidates=[
                {
                    'campus_hint': '东湖校区',
                    'address_text': '示例市东湖区大学路166号',
                },
                {
                    'campus_hint': '三元里校区',
                    'address_text': '示例市城市建设职业学校',
                },
                {
                    'campus_hint': '赤沙校区',
                    'address_text': '示例市城市建设职业学校',
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school]),
        )
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(
            result['items'][0]['place_name'],
            '示例大学东湖校区',
        )

    def test_website_module_hint_does_not_create_record(self):
        """数字校园等网站栏目线索不得生成兜底记录。"""
        school = build_school()
        page = build_page(
            'https://example.edu.cn/',
            candidates=[],
            hints=[
                '数字校园',
                '智慧校园',
                '关于校区',
                '走进校区',
                '走进校园',
                '校区分布',
                '校园分布',
                '学校导游',
                '办学地点',
                '东湖校区',
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(
            [item['place_name'] for item in result['items']],
            ['示例大学东湖校区'],
        )
        self.assertEqual(result['metrics']['item_count'], 1)

    def test_prev_next_navigation_hint_does_not_create_empty_record(self):
        """“下一条”翻页链接中的校区名不得生成无地址记录。"""
        school = build_school(school_name='广东药科大学')
        page = build_page(
            'https://www.gdpu.edu.cn/info/1013/2080.htm',
            candidates=[{
                'campus_hint': '广州校区宝岗校园',
                'address_text': '广州市海珠区宝岗光汉直街40号',
            }],
            hints=['广州校区宝岗校园', '广州校区赤岗校园'],
            related_links=[{
                'text': '下一条：广州校区赤岗校园',
                'url': 'https://www.gdpu.edu.cn/info/1013/2079.htm',
                'link_type': 'campus',
            }],
            title='广州校区宝岗校园-广东药科大学',
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(
            [
                (
                    item['place_name'],
                    item['attributes']['campus_name'],
                    item['attributes'].get('campus_name_raw'),
                    item['original_address'],
                )
                for item in result['items']
            ],
            [
                (
                    '广东药科大学宝岗校园',
                    '宝岗校园',
                    '广州校区宝岗校园',
                    '广州市海珠区宝岗光汉直街40号',
                )
            ],
        )

    def test_compound_campus_suffix_hint_is_dropped_as_alias(self):
        """“广州校区校园”是“广州校区”的冗余写法，不再生成空地址记录。"""
        school = build_school(school_name='广东岭南职业技术学院')
        page = build_page(
            'https://lnc.edu.cn/',
            candidates=[{
                'campus_hint': '广州校区',
                'address_text': '广东省广州市天河区大观中路492号',
            }],
            hints=['广州校区', '广州校区校园'],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(
            [item['attributes']['campus_name'] for item in result['items']],
            ['广州校区'],
        )
        self.assertEqual(result['metrics']['item_count'], 1)

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
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(
            [(item['attributes']['campus_name'], item['original_address'])
             for item in result['items']],
            [
                ('昌岗校区', '广州市海珠区昌岗东路257号'),
                ('大学城校区', '番禺区广州大学城外环西路168号'),
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
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(
            [item['attributes']['campus_name'] for item in result['items']],
            ['广州校区'],
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
            build_city_universities_payload([school], city='广州市'),
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

    def test_clean_drops_foreign_city_campus_record(self):
        """清洗时丢弃明确指向外市的校区记录。"""
        school = build_school(school_name='华南师范大学')
        records = [
            {
                'place_name': '华南师范大学广州校区石牌校园',
                'original_address': '广州市天河区中山大道西55号',
                'source_nature': 'web_search',
                'source_reference': 'https://www.example.edu.cn/',
                'attributes': {'campus_name': '广州校区石牌校园'},
            },
            {
                'place_name': '华南师范大学佛山校区南海校园',
                'original_address': '广东省佛山市南海区狮山镇万锦路',
                'source_nature': 'web_search',
                'source_reference': 'https://www.example.edu.cn/',
                'attributes': {'campus_name': '佛山校区南海校园'},
            },
        ]
        cleaned = clean_school_address_records(
            records, build_city_context(city='广州市')
        )
        self.assertEqual(
            [record['place_name'] for record in cleaned],
            ['华南师范大学广州校区石牌校园'],
        )

    def test_clean_drops_city_campus_with_interposed_words(self):
        """城市名与校区间夹修饰字的外市校区同样被丢弃。"""
        records = [{
            'place_name': '华南农业大学珠江学院肇庆（四会）校区',
            'original_address': '',
            'source_nature': 'web_search',
            'source_reference': 'https://www.example.edu.cn/',
            'attributes': {'campus_name': '肇庆（四会）校区'},
        }]
        cleaned = clean_school_address_records(
            records, build_city_context(city='广州市')
        )
        self.assertEqual(cleaned, [])

    def test_clean_prefers_homepage_campus_name_for_same_address(self):
        """同址多条校区写法时优先保留主页来源的校区名。"""
        school = build_school(school_name='华南师范大学')
        records = [
            {
                'place_name': '华南师范大学石牌校园',
                'original_address': '广州市天河区中山大道西55号',
                'source_nature': 'web_search',
                'source_reference': 'https://xy.example.edu.cn/news',
                'attributes': {'campus_name': '石牌校园'},
            },
            {
                'place_name': '华南师范大学广州校区石牌校园',
                'original_address': '广东省广州市天河区中山大道西55号',
                'source_nature': 'web_search',
                'source_reference': 'https://www.example.edu.cn/',
                'attributes': {'campus_name': '广州校区石牌校园'},
            },
        ]
        cleaned = clean_school_address_records(
            records, build_city_context(city='广州市')
        )
        self.assertEqual(
            cleaned[0]['attributes']['campus_name'], '广州校区石牌校园'
        )

    def test_clean_drops_office_noise_for_unlabeled_non_home_address(self):
        """无校区标签的办公点地址在非主页来源时被丢弃。"""
        school = build_school(school_name='广东邮电职业技术学院')
        records = [
            {
                'place_name': '广东邮电职业技术学院广州校区',
                'original_address': '广州市天河区中山大道西191号',
                'source_nature': 'web_search',
                'source_reference': 'https://www.example.edu.cn/',
                'attributes': {'campus_name': '广州校区'},
            },
            {
                'place_name': '广东邮电职业技术学院',
                'original_address': '广州市越秀区水荫路117号星光映景1403',
                'source_nature': 'web_search',
                'source_reference': 'https://www.example.edu.cn/info/1049/13121.htm',
                'attributes': {'campus_name': ''},
            },
        ]
        cleaned = clean_school_address_records(
            records, build_city_context(city='广州市')
        )
        self.assertEqual(
            [record['place_name'] for record in cleaned],
            ['广东邮电职业技术学院广州校区'],
        )

    def test_clean_dedupes_empty_campus_hint_records(self):
        """同一无地址校区提示只保留一条记录。"""
        school = build_school(school_name='示例大学')
        records = [
            {
                'place_name': '示例大学大学城校区',
                'original_address': '',
                'source_nature': 'web_search',
                'source_reference': 'https://www.example.edu.cn/campus',
                'attributes': {'campus_name': '大学城校区'},
            },
            {
                'place_name': '示例大学大学城校区',
                'original_address': '',
                'source_nature': 'web_search',
                'source_reference': 'https://www.example.edu.cn/about',
                'attributes': {'campus_name': '大学城校区'},
            },
        ]
        cleaned = clean_school_address_records(
            records, build_city_context(city='示例市')
        )
        self.assertEqual(len(cleaned), 1)

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

    def test_zone_city_prefix_variants_merge_before_warning(self):
        """同校区同门牌的广州/大学城写法变体应在生成阶段合并。"""
        school = build_school(
            school_name='广东药科大学',
            school_identifier='4144010573',
        )
        page = build_page(
            'https://example.edu.cn/',
            candidates=[
                {
                    'campus_hint': '广州校区大学城校园',
                    'address_text': '广州市广州大学城外环东路280号',
                },
                {
                    'campus_hint': '广州校区大学城校园',
                    'address_text': '广东省广州市大学城外环东路280号',
                },
            ],
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(result['metrics']['item_count'], 1)
        self.assertEqual(result['metrics']['warning_count'], 0)
        self.assertEqual(
            result['items'][0]['original_address'],
            '广州市广州大学城外环东路280号',
        )

    def test_hierarchical_campus_names_share_one_canonical_record(self):
        """父校区子校园写法与子校园简称合并为同一记录。"""
        school = build_school(
            school_name='广东药科大学',
            school_identifier='4144010573',
        )
        page = build_page(
            'https://www.gdpu.edu.cn/info/1013/2077.htm',
            candidates=[
                {
                    'campus_hint': '广州校区大学城校园',
                    'address_text': '广州市广州大学城外环东路280号',
                },
                {
                    'campus_hint': '大学城校园',
                    'address_text': '广东省广州市大学城外环东路280号',
                },
            ],
            title='广州校区大学城校园-广东药科大学',
        )
        result = build_address_payload(
            build_payload([build_completed_item(school, [page])]),
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(result['metrics']['item_count'], 1)
        item = result['items'][0]
        self.assertEqual(item['attributes']['campus_name'], '大学城校园')
        self.assertEqual(
            item['attributes'].get('campus_name_raw'),
            '广州校区大学城校园',
        )
        self.assertEqual(item['place_name'], '广东药科大学大学城校园')

    def test_department_room_address_merges_to_homepage_address(self):
        """学院页带房间码的地址与主页中文门牌地址合并且不留噪音。"""
        school = build_school(school_name='广州城市理工学院')
        pages = [
            build_page(
                'https://www.gcut.edu.cn/',
                candidates=[{
                    'campus_hint': '',
                    'address_text': '广州市花都区学府路一号',
                }],
                title='广州城市理工学院',
            ),
            build_page(
                'https://jx.gcut.edu.cn/jsjgcxy/list.htm',
                candidates=[{
                    'campus_hint': '',
                    'address_text': (
                        '广州市花都区学府路1号广州城市理工学院B6-312'
                    ),
                }],
                title='计算机工程学院',
            ),
        ]
        result = build_address_payload(
            build_payload([build_completed_item(school, pages)]),
            build_city_universities_payload([school], city='广州市'),
        )
        self.assertEqual(result['metrics']['item_count'], 1)
        item = result['items'][0]
        self.assertEqual(item['original_address'], '广州市花都区学府路一号')
        self.assertNotIn('B6', item['original_address'])
        self.assertNotIn('计算机工程', item['original_address'])

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

    def test_rejects_item_without_processing_status(self):
        """检索结果项缺少 processing_status 时拒绝输入。"""
        school = build_school()
        item_without_status = {
            'school_identifier': school['school_identifier'],
            'pages': [build_page('https://example.edu.cn/')],
        }
        with self.assertRaisesRegex(ValueError, 'processing_status'):
            build_address_payload(
                build_payload([item_without_status]),
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

    def test_rejects_embedded_school_object_in_item(self):
        """检索结果项必须使用 school_identifier，不得携带完整学校对象。"""
        school = build_school()
        embedded_item = {
            'school': school,
            'processing_status': 'completed',
            'pages': [build_page('https://example.edu.cn/')],
        }
        with self.assertRaisesRegex(ValueError, 'school_identifier'):
            build_address_payload(
                build_payload([embedded_item]),
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

    def test_rejects_complete_page_results_payload_as_input(self):
        """地址构建命令只接受仅含 items 的检索结果，不接受完整页面批次。"""
        school = build_school()
        page_results_payload = {
            'stage': 'university_page_results',
            'city_context': build_city_context(),
            'items': [],
        }
        with self.assertRaisesRegex(ValueError, '仅包含 items'):
            build_address_payload(
                page_results_payload,
                build_city_universities_payload([school]),
            )

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
                'build_university_address.py',
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


class UniversityAddressPostprocessTests(unittest.TestCase):
    """覆盖地图同址去重规则。"""

    def build_final_record(self, school_identifier, campus_name, final_address):
        """构造一条已解析最终地址的记录。"""
        return {
            'final_address': final_address,
            'final_address_source': 'official',
            'map_match_status': '',
            'attributes': {
                'school_identifier': school_identifier,
                'campus_name': campus_name,
            },
        }

    def test_unlabeled_distinct_addresses_are_all_kept(self):
        """同校多条无校区名不同物理地址全部保留，不再只留一条。"""
        records = [
            self.build_final_record(
                '4144010861', '', '广州市天河区天源路789号'
            ),
            self.build_final_record(
                '4144010861', '', '广州市花都区工业大道11号'
            ),
            self.build_final_record(
                '4144010861', '', '广州市天河区龙洞街道迎龙路481号'
            ),
            self.build_final_record(
                '4144010861', '', '广州市天河区天源路818号'
            ),
        ]

        result = postprocess_university_address_records(records)

        self.assertEqual(len(result), 4)

    def test_unlabeled_no_number_variant_is_dropped_with_numbered_road(self):
        """同校同路已有门牌时，无门牌无校区名的变体不再成行。"""
        numbered = self.build_final_record(
            '4144011540', '', '广州市天河区迎福路527号'
        )
        incomplete = self.build_final_record(
            '4144011540', '', '广州市天河区沙河龙洞迎福路'
        )

        result = postprocess_university_address_records(
            [numbered, incomplete]
        )

        self.assertEqual(result, [numbered])

    def test_same_school_and_map_detail_prefers_labeled_campus(self):
        """同校同地图同址时优先保留带校区名的记录。"""
        unlabeled = build_map_record(
            '4144010559',
            '',
            '广州市番禺区大学路1号',
        )
        labeled = build_map_record(
            '4144010559',
            '校本部',
            '广州市番禺区小谷围街大学路1号',
        )

        result = postprocess_university_address_records([unlabeled, labeled])

        self.assertEqual(result, [labeled])

    def test_same_address_for_different_schools_is_preserved(self):
        """不同学校的同地图地址不得互相去重。"""
        first = build_map_record('4144010001', '', '广州市天河区示例路1号')
        second = build_map_record('4144010002', '', '广州市天河区示例路1号')

        result = postprocess_university_address_records([first, second])

        self.assertEqual(result, [first, second])

    def test_sole_campus_unlabeled_and_benbu_merge_to_one_row(self):
        """单校区学校的无名主页地址与校本部地址合并保留更完整一条。"""
        homepage = {
            'final_address': '广州市白云区太和镇穗丰水均田路363号',
            'final_address_source': 'official',
            'map_match_status': '',
            'attributes': {
                'school_identifier': '4144014362',
                'campus_name': '',
            },
        }
        benbu = {
            'final_address': '广州市白云区水均田路363号',
            'final_address_source': 'official',
            'map_match_status': '',
            'attributes': {
                'school_identifier': '4144014362',
                'campus_name': '校本部',
            },
        }

        result = postprocess_university_address_records([homepage, benbu])

        self.assertEqual(len(result), 1)
        self.assertIn('太和镇穗丰水均田路363号', result[0]['final_address'])

    def test_same_campus_prefers_map_confirmed_address(self):
        """同校区多地址时地图可确证的一条优先于未验证官网地址。"""
        unverified = {
            'final_address': '广州市番禺区广州大学城外环东路208号',
            'final_address_source': 'official',
            'map_match_status': 'skipped',
            'attributes': {
                'school_identifier': '4144010573',
                'campus_name': '大学城校园',
            },
        }
        verified = {
            'final_address': '广州市番禺区大学城外环东路280号',
            'final_address_source': 'map',
            'map_match_status': 'partial',
            'attributes': {
                'school_identifier': '4144010573',
                'campus_name': '大学城校园',
            },
        }

        result = postprocess_university_address_records([unverified, verified])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], verified)

    def test_labeled_no_number_variant_is_dropped_with_numbered_road(self):
        """同校同路已有门牌时，带校区名的无门牌行也不再成行。"""
        numbered = self.build_final_record(
            '4144010861',
            '',
            '广州市花都区工业大道11号',
        )
        incomplete = self.build_final_record(
            '4144010861',
            '花都校区',
            '广州市花都区工业大道',
        )

        result = postprocess_university_address_records(
            [numbered, incomplete]
        )

        self.assertEqual(result, [numbered])

    def test_labeled_incomplete_row_loses_to_labeled_numbered_row(self):
        """同校同路已保留带门牌行时，无门牌校区行被丢弃。"""
        numbered = self.build_final_record(
            '4144013709',
            '校本部',
            '广州市环市东路465号',
        )
        incomplete = self.build_final_record(
            '4144013709',
            '广州校区',
            '广州市环市东路',
        )

        result = postprocess_university_address_records(
            [numbered, incomplete]
        )

        self.assertEqual(result, [numbered])

    def test_degenerate_road_name_does_not_drop_unrelated_campus(self):
        """中文数字路名解析退化为“路”时不得误删其它无门牌校区。"""
        numbered = self.build_final_record(
            '4144012743',
            '北校区',
            '广州市白云区钟落潭镇马沥村广从九路160号',
        )
        unnumbered = self.build_final_record(
            '4144012743',
            '东校区',
            '广州市天河区龙洞教育园区渔兴路',
        )

        result = postprocess_university_address_records(
            [numbered, unnumbered]
        )

        self.assertEqual(
            [record['attributes']['campus_name'] for record in result],
            ['北校区', '东校区'],
        )


class UniversityAddressCleaningTests(unittest.TestCase):
    """覆盖地址联系词尾巴清洗与残留检测。"""

    def test_contact_label_tail_is_cleaned_without_colon(self):
        """不带冒号的联系词尾巴应被清洗。"""
        cleaned = clean_address_text('广州市花都区工业大道11号 TEL')

        self.assertEqual(cleaned, '广州市花都区工业大道11号')
        self.assertFalse(has_contact_label_noise(cleaned))

    def test_contact_label_tail_is_cleaned_with_colon_and_number(self):
        """带冒号和电话号码的联系词尾巴应被整段清洗。"""
        cleaned = clean_address_text(
            '广州市花都区工业大道11号 TEL：020-87024621'
        )

        self.assertEqual(cleaned, '广州市花都区工业大道11号')
        self.assertFalse(has_contact_label_noise(cleaned))

    def test_postcode_label_tail_is_cleaned(self):
        """邮编标签尾巴应被清洗。"""
        cleaned = clean_address_text('广州市天河区天源路789号 邮编510650')

        self.assertEqual(cleaned, '广州市天河区天源路789号')

    def test_contact_label_noise_is_detected_before_cleaning(self):
        """清洗前残留联系词可被噪声函数识别。"""
        self.assertTrue(
            has_contact_label_noise('广州市花都区工业大道11号 TEL：')
        )
        self.assertFalse(
            has_contact_label_noise('广州市天河区环市东路465号')
        )


if __name__ == '__main__':
    unittest.main()
