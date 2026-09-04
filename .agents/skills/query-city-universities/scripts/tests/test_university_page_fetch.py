"""高校官网地址补充插件测试。"""

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from university_page_fetch import (
    build_home_identity_warning,
    build_address_candidates,
    build_university_result,
    build_campus_link_names,
    extract_campus_link_names,
    extract_campus_names,
    fetch_school_pages,
    fetch_school_pages_with_coverage,
    fetch_university_page,
    filter_related_links,
    has_campus_expansion_signal,
    has_usable_address_candidate,
    run_school_batch,
    run_session,
)
from university_campus_rules import clean_address_text


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
    @patch('university_page_fetch.fetch_official_page')
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

    @patch('university_page_fetch.OfficialPageFetcher')
    def test_session_reuses_fetcher_for_sequential_requests(self, fetcher_class):
        fetcher = fetcher_class.return_value.__enter__.return_value
        fetcher.fetch.side_effect = [
            {
                'requested_url': 'https://a.edu.cn/',
                'final_url': 'https://a.edu.cn/',
                'http_status': 200,
                'page_status': 'ok',
                'title': '甲大学',
                'official_domains': ['a.edu.cn'],
                'address_evidence': [],
                'links': [],
                'warnings': [],
            },
            {
                'requested_url': 'https://b.edu.cn/',
                'final_url': 'https://b.edu.cn/',
                'http_status': 200,
                'page_status': 'ok',
                'title': '乙大学',
                'official_domains': ['b.edu.cn'],
                'address_evidence': [],
                'links': [],
                'warnings': [],
            },
        ]
        requests = StringIO(
            '{"url":"https://a.edu.cn/","official_domains":["a.edu.cn"]}\n'
            '{"url":"https://b.edu.cn/","official_domains":["b.edu.cn"]}\n'
        )
        output = StringIO()

        run_session(requests, output)

        fetcher_class.assert_called_once_with()
        self.assertEqual(fetcher.fetch.call_count, 2)
        results = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([item['title'] for item in results], ['甲大学', '乙大学'])

    @patch('university_page_fetch.OfficialPageFetcher')
    def test_session_reuses_context_within_school(self, fetcher_class):
        """同一学校的多页共享浏览器上下文，切换学校后新建。"""
        fetcher = fetcher_class.return_value.__enter__.return_value
        context_a = Mock()
        context_b = Mock()
        fetcher.new_context.side_effect = [context_a, context_b]
        fetcher.fetch.side_effect = [
            {
                'requested_url': 'https://a.edu.cn/',
                'final_url': 'https://a.edu.cn/',
                'http_status': 200,
                'page_status': 'ok',
                'title': '甲大学',
                'official_domains': ['a.edu.cn'],
                'address_evidence': [],
                'links': [],
                'warnings': [],
            },
            {
                'requested_url': 'https://a.edu.cn/contact',
                'final_url': 'https://a.edu.cn/contact',
                'http_status': 200,
                'page_status': 'ok',
                'title': '甲大学',
                'official_domains': ['a.edu.cn'],
                'address_evidence': [],
                'links': [],
                'warnings': [],
            },
            {
                'requested_url': 'https://b.edu.cn/',
                'final_url': 'https://b.edu.cn/',
                'http_status': 200,
                'page_status': 'ok',
                'title': '乙大学',
                'official_domains': ['b.edu.cn'],
                'address_evidence': [],
                'links': [],
                'warnings': [],
            },
        ]
        requests = StringIO(
            '{"school_identifier":"4144010001","url":"https://a.edu.cn/","official_domains":["a.edu.cn"]}\n'
            '{"school_identifier":"4144010001","url":"https://a.edu.cn/contact","official_domains":["a.edu.cn"]}\n'
            '{"school_identifier":"4144010002","url":"https://b.edu.cn/","official_domains":["b.edu.cn"]}\n'
        )
        output = StringIO()

        run_session(requests, output)

        self.assertEqual(fetcher.fetch.call_count, 3)
        contexts = [call.kwargs['context'] for call in fetcher.fetch.call_args_list]
        self.assertIs(contexts[0], contexts[1])
        self.assertIsNot(contexts[0], contexts[2])
        self.assertEqual(fetcher.new_context.call_count, 2)
        self.assertEqual(context_a.close.call_count, 1)
        self.assertEqual(context_b.close.call_count, 1)
        results = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([item['title'] for item in results], ['甲大学', '甲大学', '乙大学'])

    def test_previous_heading_associates_campus(self):
        candidates = build_address_candidates([
            evidence('北京市朝阳区平乐园100号', before=('校本部',)),
        ])
        self.assertEqual(candidates[0]['campus_hint'], '校本部')

    def test_campus_address_label_associates_campus(self):
        """“东校区地址”标签可直接关联到东校区。"""
        candidates = build_address_candidates([
            evidence(
                '广州市天河区中山大道西293号',
                label='东校区地址',
            )
        ])
        self.assertEqual(candidates[0]['campus_hint'], '东校区')
        self.assertEqual(candidates[0]['association_method'], 'dom_context')

    def test_news_headline_is_not_classified_as_campus(self):
        """含校区词的新闻标题不得再被当作校区详情链接。"""
        links = [
            {
                'text': '关于五山校区临时停水的通知',
                'url': 'https://www.example.edu.cn/info/1.htm',
            },
            {
                'text': '五山校区',
                'url': 'https://www.example.edu.cn/campus/wushan.htm',
            },
            {
                'text': '校区概况',
                'url': 'https://www.example.edu.cn/xyfg/wushan/index.htm',
            },
        ]
        results = filter_related_links(
            links, ['example.edu.cn'], 'https://www.example.edu.cn/'
        )
        self.assertEqual(
            [item['text'] for item in results],
            ['五山校区', '校区概况'],
        )
        self.assertTrue(all(
            item['link_type'] == 'campus' for item in results
        ))

    def test_fee_and_institution_only_candidates_are_dropped(self):
        """费用行与整串机构名不再作为地址候选。"""
        candidates = build_address_candidates([
            evidence(
                '1600元/生·学年；清远校区：3000元/生·学年',
                label='广州校区',
            ),
            evidence('广州市城市建设职业学校', label='三元里校区'),
        ])
        self.assertEqual(candidates, [])

    def test_direction_distance_and_narrative_candidates_are_dropped(self):
        """方向距离描述与校区职责叙述不再作为地址候选。"""
        candidates = build_address_candidates([
            evidence(
                '广州市增城区增城职教园东行4千米',
                label='广州校区',
            ),
            evidence(
                '嘉禾校区，主要承担全日制本科生教育任务；'
                '滨江校区主要承担民警培训和成人教育任务',
                label='主校区',
            ),
        ])
        self.assertEqual(candidates, [])

    def test_website_module_campus_is_not_a_campus_link(self):
        """美丽校园等网站栏目不得被当作校区详情链接。"""
        results = filter_related_links(
            [
                {
                    'text': '美丽校园',
                    'url': 'https://www.example.edu.cn/beauty.htm',
                },
                {
                    'text': '南医校园',
                    'url': 'https://www.example.edu.cn/info/news.htm',
                },
                {
                    'text': '滨海校区',
                    'url': 'https://www.example.edu.cn/campus/binhai.htm',
                },
            ],
            ['example.edu.cn'],
            'https://www.example.edu.cn/',
        )
        self.assertEqual(
            [item['text'] for item in results],
            ['滨海校区'],
        )

    def test_campus_suffix_with_campus_path_still_classified(self):
        """大学城校园等校园后缀链接带校区路径时仍识别为校区链接。"""
        results = filter_related_links(
            [
                {
                    'text': '大学城校园',
                    'url': 'https://www.example.edu.cn/xyfg/dxc.htm',
                },
            ],
            ['example.edu.cn'],
            'https://www.example.edu.cn/',
        )
        self.assertEqual(
            [(item['text'], item['link_type']) for item in results],
            [('大学城校园', 'campus')],
        )

    def test_long_campus_preview_link_with_located_text_is_classified(self):
        """校区预览长链接（标题+描述含“位于”）仍识别为校区详情。"""
        results = filter_related_links(
            [
                {
                    'text': (
                        '广州校区宝岗校园 广东药科大学广州校区宝岗校园位于'
                        '广州市海珠区，临床医学院设立在该校园。'
                        '通讯地址:广州市海珠区宝岗光汉直街40号'
                    ),
                    'url': 'https://www.example.edu.cn/info/1013/2080.htm',
                },
                {
                    'text': (
                        '关于五山校区停水的通知 五山校区位于'
                        '广州市天河区五山路381号'
                    ),
                    'url': 'https://www.example.edu.cn/info/1.htm',
                },
            ],
            ['example.edu.cn'],
            'https://www.example.edu.cn/',
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['text'].startswith('广州校区宝岗校园'))
        self.assertEqual(results[0]['link_type'], 'campus')

    def test_institution_tail_after_house_number_is_stripped(self):
        """门牌号后的机构名称在地址清洗时截断。"""
        self.assertEqual(
            clean_address_text(
                '广州市白云区鹤龙二路1121号广东省培英职业技术学校'
            ),
            '广州市白云区鹤龙二路1121号',
        )


def build_school_page_result(
    url, candidates=None, related_links=None, page_status='ok', campus_hints=None,
    title='',
):
    """构造批量抓取策略使用的页面结果。"""
    return {
        'stage': 'address_candidates',
        'requested_url': url,
        'final_url': url,
        'http_status': 200,
        'page_status': page_status,
        'title': title,
        'official_domains': ['example.edu.cn'],
        'address_candidates': list(candidates or []),
        'campus_hints': list(campus_hints or []),
        'related_links': list(related_links or []),
        'warnings': [],
        'access_attempts': [],
    }


class FixedPolicyBatchFetchTests(unittest.TestCase):
    """覆盖固定页面策略、候选优先级与页数预算。"""

    def build_item(self, candidate_urls=()):
        return {
            'school_identifier': '4144010001',
            'home_url': 'https://www.example.edu.cn/',
            'official_domains': ['example.edu.cn'],
            'candidate_urls': list(candidate_urls),
        }

    def test_stops_when_home_has_address(self):
        """首页已有非空地址候选时不再补抓。"""
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            return build_school_page_result(
                url,
                candidates=[{'address_text': '广州市天河区示例路1号'}],
            )

        pages = fetch_school_pages(self.build_item(), fetch_page, max_pages=5)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(requested), 1)

    def test_continues_school_info_links_after_home_address(self):
        """首页命中地址后仍继续抓学校概况与联系页，避免漏掉其他校区。"""
        item = self.build_item()
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/'):
                return build_school_page_result(
                    url,
                    candidates=[{'address_text': '广州市天河区示例路1号'}],
                    related_links=[
                        {
                            'text': '学校概况',
                            'url': 'https://www.example.edu.cn/overview',
                            'link_type': 'overview',
                        },
                        {
                            'text': '联系我们',
                            'url': 'https://www.example.edu.cn/contact',
                            'link_type': 'contact',
                        },
                    ],
                )
            return build_school_page_result(
                url,
                candidates=[{'address_text': '广州市越秀区示例路3号'}],
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=5)
        self.assertEqual(
            requested,
            [
                'https://www.example.edu.cn/',
                'https://www.example.edu.cn/overview',
                'https://www.example.edu.cn/contact',
            ],
        )
        self.assertEqual(len(pages), 3)

    def test_school_info_link_allowlist_excludes_module_entries(self):
        """产业学院/原校/队伍等栏目简介不再作为学校概况跟随。"""
        results = filter_related_links(
            [
                {
                    'text': '原广州业余大学简介',
                    'url': 'https://www.example.edu.cn/ygdx.htm',
                },
                {
                    'text': '专精特新产业学院简介',
                    'url': 'https://www.example.edu.cn/cyxy.htm',
                },
                {
                    'text': '队伍概况',
                    'url': 'https://www.example.edu.cn/dwgk.htm',
                },
                {
                    'text': '学校概况',
                    'url': 'https://www.example.edu.cn/xxgk.htm',
                },
                {
                    'text': '学校章程',
                    'url': 'https://www.example.edu.cn/xxzc.htm',
                },
                {
                    'text': '联系我们',
                    'url': 'https://www.example.edu.cn/lxwm.htm',
                },
            ],
            ['example.edu.cn'],
            'https://www.example.edu.cn/',
        )
        self.assertEqual(
            [item['text'] for item in results],
            ['联系我们', '学校概况', '学校章程'],
        )

    def test_same_path_query_variants_are_not_fetched_twice(self):
        """同 host+path 不同 query 的自动发现链接只抓第一次。"""
        item = self.build_item()
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/'):
                return build_school_page_result(
                    url,
                    related_links=[
                        {
                            'text': '学校章程',
                            'url': (
                                'https://www.example.edu.cn/'
                                'schoolrules.html?module=a'
                            ),
                            'link_type': 'overview',
                        },
                        {
                            'text': '学校章程',
                            'url': (
                                'https://www.example.edu.cn/'
                                'schoolrules.html?module=b'
                            ),
                            'link_type': 'overview',
                        },
                    ],
                )
            return build_school_page_result(
                url,
                candidates=[{'address_text': '广州市天河区示例路1号'}],
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=5)
        self.assertEqual(
            requested,
            [
                'https://www.example.edu.cn/',
                'https://www.example.edu.cn/schoolrules.html?module=a',
            ],
        )
        self.assertEqual(len(pages), 2)

    def test_fetches_all_candidates_even_when_home_has_address(self):
        """首页已有地址时仍按 candidate_urls 顺序抓完全部候选页。"""
        item = self.build_item(candidate_urls=[
            'https://www.example.edu.cn/contact',
            'https://www.example.edu.cn/overview',
        ])
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/'):
                return build_school_page_result(
                    url,
                    candidates=[{'address_text': '广州市海珠区示例路2号'}],
                )
            return build_school_page_result(
                url,
                candidates=[{'address_text': '广州市越秀区示例路3号'}],
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=5)
        self.assertEqual(
            requested,
            [
                'https://www.example.edu.cn/',
                'https://www.example.edu.cn/contact',
                'https://www.example.edu.cn/overview',
            ],
        )
        self.assertEqual(len(pages), 3)

    def test_follows_candidate_urls_before_related_links(self):
        """首页无地址时按 candidate_urls 顺序补抓，候选页抓完后停止。"""
        item = self.build_item(candidate_urls=[
            'https://www.example.edu.cn/contact',
        ])
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/contact'):
                return build_school_page_result(
                    url,
                    candidates=[{'address_text': '广州市海珠区示例路2号'}],
                )
            return build_school_page_result(
                url,
                related_links=[
                    {'text': '联系方式', 'url': 'https://www.example.edu.cn/contact'},
                ],
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=5)
        self.assertEqual(requested[1], 'https://www.example.edu.cn/contact')
        self.assertEqual(len(pages), 2)

    def test_falls_back_to_related_links_in_page_order(self):
        """首页与候选页均无地址时，按页面返回的相关链接顺序补抓。"""
        item = self.build_item()
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/overview'):
                return build_school_page_result(
                    url,
                    candidates=[{'address_text': '广州市越秀区示例路3号'}],
                )
            return build_school_page_result(
                url,
                related_links=[
                    {'text': '联系方式', 'url': 'https://www.example.edu.cn/contact'},
                    {'text': '学校概况', 'url': 'https://www.example.edu.cn/overview'},
                ],
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=5)
        self.assertEqual(requested[1], 'https://www.example.edu.cn/contact')
        self.assertEqual(requested[2], 'https://www.example.edu.cn/overview')
        self.assertEqual(len(pages), 3)

    def test_respects_max_pages_budget(self):
        """持续无地址时总页数不超过 max_pages，失败页也计入预算。"""
        item = self.build_item(candidate_urls=[
            'https://www.example.edu.cn/contact',
            'https://www.example.edu.cn/overview',
        ])
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            return build_school_page_result(
                url,
                page_status='http_error',
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=3)
        self.assertEqual(len(pages), 3)
        self.assertEqual(len(requested), 3)

    def test_skips_urls_outside_official_domains(self):
        """candidate_urls 与相关链接中的跨域 URL 不抓取。"""
        item = {
            'school_identifier': '4144010001',
            'home_url': 'https://www.example.edu.cn/',
            'official_domains': ['example.edu.cn'],
            'candidate_urls': ['https://other.example.net/'],
        }
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            return build_school_page_result(
                url,
                related_links=[
                    {'text': '外部', 'url': 'https://other.example.net/contact'},
                ],
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=5)
        self.assertEqual(requested, ['https://www.example.edu.cn/'])
        self.assertEqual(len(pages), 1)

    def test_has_usable_address_candidate(self):
        """非空地址候选判定只认 address_text。"""
        self.assertTrue(has_usable_address_candidate(build_school_page_result(
            'https://www.example.edu.cn/',
            candidates=[{'address_text': '广州市天河区示例路1号'}],
        )))
        self.assertFalse(has_usable_address_candidate(build_school_page_result(
            'https://www.example.edu.cn/',
            candidates=[{'address_text': '  '}],
        )))

    def test_campus_expansion_signal_sees_multi_campus_with_address(self):
        """页面已有地址但显示多校区线索时仍触发扩展。"""
        self.assertTrue(has_campus_expansion_signal(build_school_page_result(
            'https://www.example.edu.cn/',
            campus_hints=['五山校区', '大学城校区'],
        )))
        self.assertTrue(has_campus_expansion_signal(build_school_page_result(
            'https://www.example.edu.cn/',
            related_links=[
                {
                    'text': '五山校区',
                    'url': 'https://www.example.edu.cn/wushan',
                    'link_type': 'campus',
                },
                {
                    'text': '大学城校区',
                    'url': 'https://www.example.edu.cn/dxc',
                    'link_type': 'campus',
                },
            ],
        )))
        self.assertTrue(has_campus_expansion_signal(build_school_page_result(
            'https://www.example.edu.cn/',
            candidates=[{'address_text': '广州市天河区示例路1号'}],
            campus_hints=['五山校区', '大学城校区'],
        )))
        self.assertFalse(has_campus_expansion_signal(build_school_page_result(
            'https://www.example.edu.cn/',
            campus_hints=['校本部'],
        )))
        self.assertTrue(has_campus_expansion_signal(build_school_page_result(
            'https://www.example.edu.cn/',
            candidates=[
                {'address_text': '广州市海珠区昌岗东路257号'},
                {'address_text': '番禺区广州大学城外环西路168号'},
            ],
        )))
        self.assertFalse(has_campus_expansion_signal(build_school_page_result(
            'https://www.example.edu.cn/',
            candidates=[{'address_text': '广州市天河区示例路1号'}],
        )))

    def test_home_identity_warning_flags_title_mismatch(self):
        """首页标题缺少学校名称时给出身份校验警告。"""
        warning = build_home_identity_warning(
            build_school_page_result(
                'https://www.example.edu.cn/',
                title='欢迎访问示例大学官方网站',
            ),
            '示例大学',
        )
        self.assertEqual(warning, '')
        warning = build_home_identity_warning(
            build_school_page_result(
                'https://www.example.edu.cn/',
                title='Other University',
            ),
            '示例大学',
        )
        self.assertTrue(warning.startswith('页面身份校验：'))

    def test_home_identity_warning_allows_parenthetical_core(self):
        """括号校区/合作标注不影响校名核心匹配。"""
        warning = build_home_identity_warning(
            build_school_page_result(
                'https://www.example.edu.cn/',
                title='香港科技大学',
            ),
            '香港科技大学（广州）',
        )
        self.assertEqual(warning, '')

    def test_fetch_school_pages_appends_identity_warning_for_home(self):
        """批量抓取时身份校验警告写入首页页面结果。"""
        item = self.build_item()
        item['school_name'] = '示例大学'

        def fetch_page(url, domains):
            return build_school_page_result(
                url,
                title='Other University',
                candidates=[{'address_text': '广州市天河区示例路1号'}],
            )

        pages = fetch_school_pages(item, fetch_page, max_pages=5)
        self.assertTrue(any(
            str(warning or '').startswith('页面身份校验：')
            for warning in pages[0].get('warnings') or []
        ))

    def test_campus_expansion_raises_budget_from_3_to_6(self):
        """多校区汇总页无地址时预算从 3 页放宽到 6 页。"""
        item = self.build_item()
        requested = []
        campus_urls = [
            f'https://www.example.edu.cn/campus-{index}'
            for index in range(5)
        ]

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/'):
                return build_school_page_result(
                    url,
                    related_links=[
                        {
                            'text': f'{name}校区',
                            'url': campus_url,
                            'link_type': 'campus',
                        }
                        for name, campus_url in zip(
                            ('一', '二', '三', '四', '五'),
                            campus_urls,
                        )
                    ],
                )
            return build_school_page_result(url)

        pages = fetch_school_pages(item, fetch_page, max_pages=3)
        self.assertEqual(len(pages), 6)
        self.assertEqual(len(requested), 6)

    def test_campus_expansion_deduplicates_same_campus(self):
        """同一校区多个详情链接只补抓第一个。"""
        item = self.build_item()
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/'):
                return build_school_page_result(
                    url,
                    related_links=[
                        {
                            'text': '五山校区',
                            'url': 'https://www.example.edu.cn/wushan-a',
                            'link_type': 'campus',
                        },
                        {
                            'text': '五山校区',
                            'url': 'https://www.example.edu.cn/wushan-b',
                            'link_type': 'campus',
                        },
                    ],
                )
            return build_school_page_result(url)

        pages = fetch_school_pages(item, fetch_page, max_pages=3)
        self.assertEqual(
            requested,
            [
                'https://www.example.edu.cn/',
                'https://www.example.edu.cn/wushan-a',
            ],
        )
        self.assertEqual(len(pages), 2)

    def test_charter_enumeration_does_not_pair_by_context(self):
        """章程多校区枚举文本不得把法定地址猜测成任一校区。"""
        candidates = build_address_candidates([
            evidence(
                '广州市海珠区宝岗光汉直街40号',
                raw=(
                    '第三条 学校法定注册地址为广州市海珠区宝岗光汉直街40号。\n'
                    '学校设有三个校区五个校园，分别是广州校区'
                    '（大学城校园、赤岗校园、宝岗校园）、'
                    '中山校区（校园）和云浮校区（校园）。'
                ),
            )
        ])
        self.assertEqual(candidates[0]['campus_hint'], '')
        self.assertEqual(candidates[0]['association_method'], 'unmatched')

    def test_in_city_campus_pages_precede_overview_and_foreign_campus(self):
        """同城校区详情页优先于概况/章程，外市校区最后抓取。"""
        item = self.build_item(candidate_urls=[
            'https://www.example.edu.cn/campuses.htm',
            'https://www.example.edu.cn/charter.htm',
        ])
        item['target_city'] = '广州市'
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/campuses.htm'):
                return build_school_page_result(
                    url,
                    related_links=[
                        {
                            'text': (
                                '大学城校区 广东药科大学广州校区大学城校园'
                                '座落在广州市番禺区广州大学城，是学校的主校区。'
                            ),
                            'url': 'https://www.example.edu.cn/dxc.htm',
                            'link_type': 'campus',
                        },
                        {
                            'text': (
                                '赤岗校区 广东药科大学广州校区赤岗校园位于'
                                '广州市海珠区赤岗江海大道中。'
                            ),
                            'url': 'https://www.example.edu.cn/chigang.htm',
                            'link_type': 'campus',
                        },
                        {
                            'text': (
                                '中山校区 广东药科大学中山校区，座落在中山市'
                                '五桂山风景区。'
                            ),
                            'url': 'https://www.example.edu.cn/zhongshan.htm',
                            'link_type': 'campus',
                        },
                        {
                            'text': '学校概况',
                            'url': 'https://www.example.edu.cn/overview.htm',
                            'link_type': 'overview',
                        },
                    ],
                )
            if url.endswith('/charter.htm') or url.endswith('/overview.htm'):
                return build_school_page_result(
                    url,
                    candidates=[{'address_text': '广州市天河区示例路1号'}],
                )
            return build_school_page_result(url)

        pages, coverage = fetch_school_pages_with_coverage(
            item,
            fetch_page,
            max_pages=8,
            target_city='广州市',
        )
        self.assertEqual(
            requested,
            [
                'https://www.example.edu.cn/',
                'https://www.example.edu.cn/campuses.htm',
                'https://www.example.edu.cn/dxc.htm',
                'https://www.example.edu.cn/chigang.htm',
                'https://www.example.edu.cn/charter.htm',
                'https://www.example.edu.cn/overview.htm',
                'https://www.example.edu.cn/zhongshan.htm',
            ],
        )
        self.assertEqual(coverage['enumerated_campus_count'], 3)
        self.assertEqual(coverage['missing_campus_names'], [])

    def test_campus_link_name_extracts_head_before_long_description(self):
        """campus 链接文本带长简介时仍取首段校区名。"""
        link = {
            'text': (
                '广州校区宝岗校园 广东药科大学广州校区宝岗校园位于广州市'
                '海珠区。临床医学院设立在该校园，开设有临床医学等专业。'
            ),
            'url': 'https://www.example.edu.cn/info/2080.htm',
            'link_type': 'campus',
        }
        self.assertEqual(
            build_campus_link_names(link),
            ['广州校区宝岗校园'],
        )

    def test_campus_detail_page_does_not_expand_campus_links(self):
        """校区详情页不再扩展校区子链接，避免挤占其他枚举校区预算。"""
        item = self.build_item()
        requested = []

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/'):
                return build_school_page_result(
                    url,
                    related_links=[
                        {
                            'text': '佛山校区',
                            'url': 'https://www.example.edu.cn/foshan.htm',
                            'link_type': 'campus',
                        },
                        {
                            'text': '汕尾校区',
                            'url': 'https://www.example.edu.cn/shanwei.htm',
                            'link_type': 'campus',
                        },
                    ],
                )
            if url.endswith('/foshan.htm'):
                return build_school_page_result(
                    url,
                    related_links=[
                        {
                            'text': '佛山校区南海校园',
                            'url': (
                                'https://www.example.edu.cn/'
                                'foshan-nanhai.htm'
                            ),
                            'link_type': 'campus',
                        },
                    ],
                )
            return build_school_page_result(url)

        pages, coverage = fetch_school_pages_with_coverage(
            item,
            fetch_page,
            max_pages=6,
            target_city='广州市',
        )
        self.assertEqual(
            requested,
            [
                'https://www.example.edu.cn/',
                'https://www.example.edu.cn/foshan.htm',
                'https://www.example.edu.cn/shanwei.htm',
            ],
        )
        self.assertEqual(len(pages), 3)
        self.assertEqual(
            set(coverage['fetched_campus_names']),
            {'佛山校区', '汕尾校区'},
        )

    def test_campus_coverage_reports_missing_in_city_campus(self):
        """预算不足漏抓同城校区时产生缺失告警且外市校区不计入。"""
        item = self.build_item(candidate_urls=[
            'https://www.example.edu.cn/campuses.htm',
        ])
        requested = []
        campus_names = (
            '大学城', '赤岗', '宝岗', '白云', '天河',
        )
        foreign_name = '中山'

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/campuses.htm'):
                return build_school_page_result(
                    url,
                    related_links=[
                        {
                            'text': f'{name}校区',
                            'url': f'https://www.example.edu.cn/{name}.htm',
                            'link_type': 'campus',
                        }
                        for name in campus_names + (foreign_name,)
                    ],
                )
            return build_school_page_result(url)

        pages, coverage = fetch_school_pages_with_coverage(
            item,
            fetch_page,
            max_pages=6,
            target_city='广州市',
        )
        self.assertEqual(len(pages), 6)
        self.assertEqual(coverage['enumerated_campus_count'], 6)
        self.assertEqual(
            set(coverage['fetched_campus_names']),
            {f'{name}校区' for name in campus_names[:4]},
        )
        self.assertEqual(coverage['missing_campus_names'], ['天河校区'])

    def test_campus_coverage_separates_missing_address_from_missing_page(self):
        """详情页未抓但地址已由其他页面采到时只记录信息字段。"""
        item = self.build_item(candidate_urls=[
            'https://www.example.edu.cn/campuses.htm',
        ])
        requested = []
        campus_names = (
            '大学城', '赤岗', '宝岗', '白云', '天河',
        )

        def fetch_page(url, domains):
            requested.append(url)
            if url.endswith('/campuses.htm'):
                return build_school_page_result(
                    url,
                    candidates=[
                        {
                            'campus_hint': f'{name}校区',
                            'address_text': f'广州市白云区{name}路1号',
                        }
                        for name in campus_names
                    ],
                    related_links=[
                        {
                            'text': f'{name}校区',
                            'url': f'https://www.example.edu.cn/{name}.htm',
                            'link_type': 'campus',
                        }
                        for name in campus_names
                    ],
                )
            return build_school_page_result(url)

        pages, coverage = fetch_school_pages_with_coverage(
            item,
            fetch_page,
            max_pages=6,
            target_city='广州市',
        )
        self.assertEqual(len(pages), 6)
        self.assertEqual(coverage['enumerated_campus_count'], 5)
        self.assertEqual(coverage['missing_campus_names'], [])
        self.assertEqual(
            coverage['detail_page_not_fetched'],
            ['天河校区'],
        )

    @patch('university_page_fetch.fetch_school_pages_with_coverage')
    @patch('university_page_fetch.OfficialPageFetcher')
    def test_run_school_batch_writes_completed_result_file(
        self, fetcher_class, fetch_school_pages_mock
    ):
        """批量模式把完整页面对象原子写入 school_results/<id>.json。"""
        pages = [build_school_page_result(
            'https://www.example.edu.cn/',
            candidates=[{'address_text': '广州市天河区示例路1号'}],
        )]
        fetch_school_pages_mock.return_value = (
            pages,
            {
                'enumerated_campus_count': 0,
                'fetched_campus_names': [],
                'missing_campus_names': [],
            },
        )
        fetcher = fetcher_class.return_value.__enter__.return_value
        context = fetcher.new_context.return_value

        with tempfile.TemporaryDirectory() as directory:
            summaries = run_school_batch(
                [self.build_item()],
                directory,
                max_pages=3,
            )
            output_path = Path(directory) / 'school_results' / '4144010001.json'
            payload = json.loads(output_path.read_text(encoding='utf-8'))

        self.assertEqual(summaries[0]['page_count'], 1)
        self.assertTrue(summaries[0]['has_address_candidate'])
        self.assertEqual(payload['processing_status'], 'completed')
        self.assertEqual(payload['pages'], pages)
        context.close.assert_called_once_with()

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

    def test_website_module_word_is_not_a_campus_name(self):
        """数字校园等网站栏目词不得作为校区名。"""
        self.assertEqual(extract_campus_names('数字校园'), [])
        self.assertEqual(extract_campus_names('智慧校园'), [])
        self.assertEqual(extract_campus_names('走进校园'), [])
        self.assertEqual(extract_campus_names('校区分布'), [])
        self.assertEqual(extract_campus_names('校园分布'), [])
        self.assertEqual(
            extract_campus_names('广州科技贸易职业学院数字校园'),
            [],
        )

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

    def test_campus_prefix_before_located_sentence_is_extracted(self):
        """“学校名+校区名位于…”句式可提取校区名供标题节关联。"""
        self.assertEqual(
            extract_campus_names(
                '广东药科大学广州校区宝岗校园位于广州市海珠区。'
            ),
            ['广州校区宝岗校园'],
        )

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

    def test_related_links_ignore_prev_next_navigation(self):
        """翻页导航链接不得作为校区线索或后续抓取目标。"""
        links = [
            {
                'text': '下一条：广州校区赤岗校园',
                'url': 'https://example.edu.cn/info/2079.htm',
                'link_type': 'campus',
            },
            {
                'text': '上一条：中山校区',
                'url': 'https://example.edu.cn/info/2078.htm',
                'link_type': 'campus',
            },
            {
                'text': '学校校区',
                'url': 'https://example.edu.cn/campuses.htm',
                'link_type': 'campus',
            },
        ]
        results = filter_related_links(
            links, ['example.edu.cn'], 'https://example.edu.cn/info/2080.htm'
        )
        self.assertEqual(
            [item['text'] for item in results],
            ['学校校区'],
        )

    def test_navigation_link_does_not_become_campus_hint(self):
        """旧版页面中“下一条”校区链接不再生成孤立校区提示。"""
        result = build_university_result({
            'requested_url': 'https://example.edu.cn/info/2080.htm',
            'final_url': 'https://example.edu.cn/info/2080.htm',
            'http_status': 200,
            'page_status': 'ok',
            'title': '广州校区宝岗校园-广东药科大学',
            'official_domains': ['example.edu.cn'],
            'address_evidence': [],
            'links': [{
                'text': '下一条：广州校区赤岗校园',
                'url': 'https://example.edu.cn/info/2079.htm',
            }],
            'warnings': [],
        })
        self.assertEqual(result['campus_hints'], ['广州校区宝岗校园'])
        self.assertEqual(
            [link['text'] for link in result['related_links']],
            [],
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
