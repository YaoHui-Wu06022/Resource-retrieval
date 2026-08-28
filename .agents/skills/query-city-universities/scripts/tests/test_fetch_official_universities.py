"""高校官网地址补充插件测试。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_official_universities import (
    build_address_candidates,
    build_university_result,
    extract_campus_link_names,
    extract_campus_names,
    fetch_university_page,
    filter_related_links,
)


def evidence(address, label='', before=(), after=(), raw='', region='semantic_footer'):
    """构造公共地址证据。"""
    return {
        'address_text': address,
        'raw_text': raw or address,
        'label_text': label,
        'extraction_method': 'footer_contact',
        'source_region': region,
        'visible': True,
        'context_before': [{'text': item} for item in before],
        'context_after': [{'text': item} for item in after],
    }


class FetchOfficialPagePluginTests(unittest.TestCase):
    @patch('fetch_official_universities.fetch_official_page')
    def test_university_fetch_enables_both_campus_label_forms(self, fetch_page):
        fetch_page.return_value = {
            'requested_url': 'https://example.edu.cn/',
            'final_url': 'https://example.edu.cn/',
            'http_status': 200,
            'page_status': 'ok',
            'title': '示例大学',
            'official_domains': ['example.edu.cn'],
            'address_evidence': [],
            'links': [],
            'warnings': [],
        }
        fetch_university_page('https://example.edu.cn/', ['example.edu.cn'])
        labels = fetch_page.call_args.kwargs['extra_address_labels']
        self.assertIn('校区', labels)
        self.assertIn('校园', labels)

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

    def test_university_town_is_not_treated_as_school_name_prefix(self):
        self.assertEqual(extract_campus_names('广州校区大学城校园'), ['广州校区大学城校园'])

    def test_generic_school_campus_is_not_a_campus_name(self):
        self.assertEqual(extract_campus_names('学校校区'), [])

    def test_generic_campus_navigation_label_is_not_a_campus_name(self):
        self.assertEqual(extract_campus_names('图说校区'), [])

    def test_campus_reference_sentence_is_not_a_campus_name(self):
        self.assertEqual(extract_campus_names('临床医学院设立在该校园'), [])

    def test_inline_suffix_associates_campus(self):
        candidates = build_address_candidates([
            evidence('贵阳市花溪区大职路', raw='贵阳市花溪区大职路（花溪校区）'),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '花溪校区')
        self.assertEqual(candidates[0]['address_text'], '贵阳市花溪区大职路')

    def test_campus_suffix_removes_preceding_postcode(self):
        candidates = build_address_candidates([
            evidence(
                '广东省广州市海珠区仑头路21号 510320(广州校区)',
                label='广州校区',
            ),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '广州校区')
        self.assertEqual(candidates[0]['address_text'], '广东省广州市海珠区仑头路21号')

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

    def test_campus_prefix_inside_address_value_is_removed(self):
        candidates = build_address_candidates([
            evidence(
                '校本部：广东省广州市番禺区小谷围街广州大学城外环西路100号',
                raw='第五条 学校地址：\n校本部：广东省广州市番禺区小谷围街广州大学城外环西路100号',
            ),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '校本部')
        self.assertEqual(
            candidates[0]['address_text'],
            '广东省广州市番禺区小谷围街广州大学城外环西路100号',
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

    def test_space_separated_parenthesized_campus_addresses_are_split(self):
        candidates = build_address_candidates([
            evidence(
                '广州市海珠区新港西路152号（广州校区） '
                '佛山市南海区南海软件科技园（南海校区）',
                label='学校地址',
            )
        ])
        self.assertEqual(
            [(item['campus_hint'], item['address_text']) for item in candidates],
            [
                ('广州校区', '广州市海珠区新港西路152号'),
                ('南海校区', '佛山市南海区南海软件科技园'),
            ],
        )

    def test_space_separated_named_campus_addresses_are_split(self):
        candidates = build_address_candidates([
            evidence(
                '广州市从化区从化大道南79号',
                raw='校本部：广州市环市东路465号 '
                '从化校区：广州市从化区从化大道南79号',
                label='地址',
            )
        ])
        self.assertEqual(
            [(item['campus_hint'], item['address_text']) for item in candidates],
            [
                ('校本部', '广州市环市东路465号'),
                ('从化校区', '广州市从化区从化大道南79号'),
            ],
        )

    def test_common_layer_split_named_addresses_are_not_split_again(self):
        raw = (
            '广州校区：广州市增城区华立路7号 电话：020-82906888 '
            '云浮校区：云浮市云祥大道53号 电话：0766-32801002'
        )
        candidates = build_address_candidates([
            evidence('广州市增城区华立路7号', raw=raw, label='广州校区'),
            evidence(
                '云浮市云祥大道53号', raw=raw,
                label='电话：020-82906888 云浮校区',
            ),
        ])
        self.assertEqual(
            [(item['campus_hint'], item['address_text']) for item in candidates],
            [
                ('广州校区', '广州市增城区华立路7号'),
                ('云浮校区', '云浮市云祥大道53号'),
            ],
        )

    def test_formal_charter_campus_location_clauses_are_split(self):
        candidates = build_address_candidates([
            evidence(
                '广东省广州市越秀区下塘西路1号',
                raw=(
                    '学校法定住所为广东省广州市越秀区下塘西路1号。'
                    '中山市五桂山校区（主校区）位于广东省中山市五桂山区丹桂路3号，'
                    '广州市越秀区校区位于广东省广州市越秀区下塘西路1号，'
                    '广州市白云山校区位于广东省广州市白云区云泉路162号，'
                    '佛山市南海区校区位于广东省佛山市南海区桂城南新三路2号。'
                ),
                label='学校法定住所',
            )
        ])
        self.assertEqual(
            [(item['campus_hint'], item['address_text']) for item in candidates],
            [
                ('中山市五桂山校区（主校区）', '广东省中山市五桂山区丹桂路3号'),
                ('广州市越秀区校区', '广东省广州市越秀区下塘西路1号'),
                ('广州市白云山校区', '广东省广州市白云区云泉路162号'),
                ('佛山市南海区校区', '广东省佛山市南海区桂城南新三路2号'),
            ],
        )

    def test_campus_detail_title_selects_matching_slash_address(self):
        candidates = build_address_candidates(
            [evidence(
                '广州市海珠区昌岗东路257号 / 番禺区广州大学城外环西路168号'
            )],
            page_title='昌岗校区-示例大学',
        )
        self.assertEqual(
            [(item['campus_hint'], item['address_text']) for item in candidates],
            [('昌岗校区', '广州市海珠区昌岗东路257号')],
        )

    def test_unmatched_address_is_preserved(self):
        candidate = build_address_candidates([evidence('深圳市南山区科研路1号')])[0]
        self.assertEqual(candidate['campus_hint'], '')
        self.assertEqual(candidate['association_method'], 'unmatched')

    def test_promotional_sentence_is_not_campus(self):
        self.assertEqual(extract_campus_names('憧憬踏入美丽的示例大学校园'), [])

    def test_long_news_link_does_not_create_campus_hint(self):
        self.assertEqual(
            extract_campus_link_names(
                '直达广深机场！广州新华师生快车道上新，东莞校区师生出行更方便'
            ),
            [],
        )

    def test_related_links_are_same_domain_and_bounded(self):
        links = [
            {'text': '滨海校区', 'url': 'https://example.edu.cn/campus.htm'},
            {'text': '学校导游', 'url': 'https://example.edu.cn/guide.htm'},
            {'text': '校园生活', 'url': 'https://example.edu.cn/life.htm'},
            {'text': '联系我们', 'url': 'https://example.edu.cn/contact.htm'},
            {'text': '学校章程', 'url': 'https://example.edu.cn/charter.htm'},
            {'text': '学校概况', 'url': 'https://outside.test/about.htm'},
        ]
        results = filter_related_links(links, ['example.edu.cn'], 'https://example.edu.cn/')
        self.assertEqual(
            [item['text'] for item in results],
            ['滨海校区', '学校导游', '联系我们', '学校章程'],
        )

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

    def test_body_address_uses_campus_detail_page_title_as_fallback(self):
        result = build_university_result({
            'requested_url': 'https://example.edu.cn/campus.htm',
            'final_url': 'https://example.edu.cn/campus.htm',
            'http_status': 200,
            'page_status': 'ok',
            'title': '广州校区大学城校园-示例大学',
            'official_domains': ['example.edu.cn'],
            'address_evidence': [evidence(
                '广州市番禺区大学城外环东路280号', region='body'
            )],
            'links': [],
            'warnings': [],
        })
        self.assertEqual(result['address_candidates'][0]['campus_hint'], '广州校区大学城校园')
        self.assertEqual(result['address_candidates'][0]['association_method'], 'page_title')

    def test_campus_page_title_is_preserved_as_fallback_hint(self):
        result = build_university_result({
            'requested_url': 'https://example.edu.cn/campus.htm',
            'final_url': 'https://example.edu.cn/campus.htm',
            'http_status': 200,
            'page_status': 'ok',
            'title': '示例大学肇庆校区',
            'official_domains': ['example.edu.cn'],
            'address_evidence': [],
            'links': [],
            'warnings': [],
        })
        self.assertEqual(result['campus_hints'], ['肇庆校区'])

    def test_campus_title_before_site_suffix_is_preserved_as_hint(self):
        result = build_university_result({
            'requested_url': 'https://example.edu.cn/campus.htm',
            'final_url': 'https://example.edu.cn/campus.htm',
            'http_status': 200,
            'page_status': 'ok',
            'title': '沙河校区-示例大学专题网站',
            'official_domains': ['example.edu.cn'],
            'address_evidence': [],
            'links': [],
            'warnings': [],
        })
        self.assertEqual(result['campus_hints'], ['沙河校区'])

    def test_campus_title_after_school_name_is_preserved_as_hint(self):
        result = build_university_result({
            'requested_url': 'https://example.edu.cn/campus.htm',
            'final_url': 'https://example.edu.cn/campus.htm',
            'http_status': 200,
            'page_status': 'ok',
            'title': '示例大学-江门校区',
            'official_domains': ['example.edu.cn'],
            'address_evidence': [],
            'links': [],
            'warnings': [],
        })
        self.assertEqual(result['campus_hints'], ['江门校区'])


if __name__ == '__main__':
    unittest.main()
