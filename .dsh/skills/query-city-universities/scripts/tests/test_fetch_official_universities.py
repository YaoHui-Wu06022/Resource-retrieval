"""高校官网地址补充插件测试。"""

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_official_universities import (
    build_address_candidates,
    build_university_result,
    extract_campus_names,
    filter_related_links,
)


def evidence(address, label='', before=(), after=(), raw=''):
    """构造公共地址证据。"""
    return {
        'address_text': address,
        'raw_text': raw or address,
        'label_text': label,
        'extraction_method': 'footer_contact',
        'source_region': 'semantic_footer',
        'visible': True,
        'context_before': [{'text': item} for item in before],
        'context_after': [{'text': item} for item in after],
    }


class FetchOfficialPagePluginTests(unittest.TestCase):
    def test_previous_heading_associates_campus(self):
        candidates = build_address_candidates([
            evidence('北京市朝阳区平乐园100号', before=('校本部',)),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '校本部')

    def test_label_associates_campus(self):
        candidates = build_address_candidates([
            evidence('郑州市郑东新区郑开大道66号', label='象湖校区地址'),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '象湖校区')

    def test_spaced_label_associates_normalized_campus(self):
        candidates = build_address_candidates([
            evidence('湖南省长沙市天心区万家丽南路二段960号', label='云 塘 校 区'),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '云塘校区')

    def test_ascii_or_postcode_prefix_does_not_pollute_campus(self):
        self.assertEqual(extract_campus_names('reserved成都校区'), ['成都校区'])
        self.assertEqual(extract_campus_names('610100德阳校区'), ['德阳校区'])

    def test_school_name_prefix_does_not_pollute_campus(self):
        self.assertEqual(extract_campus_names('新疆大学喀什校区'), ['喀什校区'])
        self.assertEqual(extract_campus_names('华南理工大学大学城校区'), ['大学城校区'])

    def test_inline_suffix_associates_campus(self):
        candidates = build_address_candidates([
            evidence('贵阳市花溪区大职路', raw='贵阳市花溪区大职路（花溪校区）'),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '花溪校区')
        self.assertEqual(candidates[0]['address_text'], '贵阳市花溪区大职路')

    def test_parenthesized_campus_address_is_split(self):
        candidates = build_address_candidates([
            evidence('示例大学南山校区(重庆市南岸区南山街道崇教路1号) 400065')
        ])
        self.assertEqual(candidates[0]['campus_hint'], '南山校区')
        self.assertEqual(candidates[0]['address_text'], '重庆市南岸区南山街道崇教路1号')

    def test_leading_parenthesized_campus_is_removed_from_address(self):
        candidates = build_address_candidates([
            evidence(
                '( 南华大学红湘校区 ) 湖南省衡阳市常胜西路28号',
                label='学院地址',
                before=('红湘校区',),
            )
        ])
        self.assertEqual(candidates[0]['campus_hint'], '红湘校区')
        self.assertEqual(candidates[0]['address_text'], '湖南省衡阳市常胜西路28号')

    def test_inline_prefix_wins_over_neighboring_campus_address(self):
        candidates = build_address_candidates([
            evidence(
                '凯江校区：四川省德阳市旌阳区凯江路二段32号',
                before=('青衣江校区：四川省德阳市旌阳区青衣江东路一段333号',),
            ),
            evidence(
                '青衣江校区：四川省德阳市旌阳区青衣江东路一段333号',
                after=('凯江校区：四川省德阳市旌阳区凯江路二段32号',),
            ),
        ])
        by_campus = {item['campus_hint']: item for item in candidates}
        self.assertEqual(
            by_campus['凯江校区']['address_text'],
            '四川省德阳市旌阳区凯江路二段32号',
        )
        self.assertEqual(
            by_campus['青衣江校区']['address_text'],
            '四川省德阳市旌阳区青衣江东路一段333号',
        )
        self.assertEqual(
            by_campus['凯江校区']['association_method'],
            'inline_campus_prefix',
        )

    def test_multiline_contact_block_is_not_inline_campus_prefix(self):
        candidate = build_address_candidates([
            evidence(
                '兰州市兰州新区长江大道东段1942号 七里河校区：兰州市七里河区龚家坪东路1号',
                raw=(
                    '联系地址\n兰州新区校区：\n兰州市兰州新区长江大道东段1942号\n'
                    '七里河校区：\n兰州市七里河区龚家坪东路1号'
                ),
            ),
        ])[0]
        self.assertNotEqual(candidate['association_method'], 'inline_campus_prefix')

    def test_inline_campus_prefix_without_address_is_discarded(self):
        candidates = build_address_candidates([evidence('七里河校区：')])
        self.assertEqual(candidates, [])

    def test_school_prefixed_inline_campus_is_removed_from_address(self):
        candidates = build_address_candidates([
            evidence(
                '新疆大学乌鲁木齐校区红湖校园：乌鲁木齐市天山区胜利路666号',
                raw='新疆大学乌鲁木齐校区红湖校园：乌鲁木齐市天山区胜利路666号\n（邮政编码：830046）',
            ),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '乌鲁木齐校区红湖校园')
        self.assertEqual(candidates[0]['address_text'], '乌鲁木齐市天山区胜利路666号')

    def test_pipe_separated_campus_addresses_are_split(self):
        candidates = build_address_candidates([
            evidence(
                '西安市西长安街558号（长安校区）| 西安市长安南路300号（雁塔校区）',
                label='地址',
            )
        ])
        self.assertEqual(
            [(item['campus_hint'], item['address_text']) for item in candidates],
            [
                ('长安校区', '西安市西长安街558号'),
                ('雁塔校区', '西安市长安南路300号'),
            ],
        )

    def test_unmatched_address_is_preserved(self):
        candidate = build_address_candidates([evidence('深圳市南山区科研路1号')])[0]
        self.assertEqual(candidate['campus_hint'], '')
        self.assertEqual(candidate['association_method'], 'unmatched')

    def test_promotional_sentence_is_not_campus(self):
        self.assertEqual(extract_campus_names('憧憬踏入美丽的示例大学校园'), [])

    def test_related_links_are_same_domain_and_bounded(self):
        links = [
            {'text': '滨海校区', 'url': 'https://example.edu.cn/campus.htm'},
            {'text': '校园生活', 'url': 'https://example.edu.cn/life.htm'},
            {'text': '联系我们', 'url': 'https://example.edu.cn/contact.htm'},
            {'text': '学校概况', 'url': 'https://outside.test/about.htm'},
        ]
        results = filter_related_links(links, ['example.edu.cn'], 'https://example.edu.cn/')
        self.assertEqual([item['text'] for item in results], ['滨海校区', '联系我们'])

    def test_common_http_status_is_preserved(self):
        result = build_university_result({
            'requested_url': 'https://example.edu.cn/',
            'final_url': 'https://example.edu.cn/',
            'http_status': 429,
            'page_status': 'http_error',
            'title': '429',
            'official_domains': ['example.edu.cn'],
            'address_evidence': [],
            'links': [],
            'warnings': ['页面返回 HTTP 429'],
        })
        self.assertEqual(result['page_status'], 'http_error')
        self.assertEqual(result['warnings'], ['页面返回 HTTP 429'])


if __name__ == '__main__':
    unittest.main()
