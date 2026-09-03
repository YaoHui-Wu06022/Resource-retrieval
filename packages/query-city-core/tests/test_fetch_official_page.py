"""官网页面通用地址证据提取测试。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from query_city_core.web.fetch_official_page import (  # noqa: E402
    OfficialPageFetcher,
    build_page_result,
    collect_official_page_data,
    decode_html_content,
    fetch_browser_page,
    fetch_http_page,
    fetch_official_page,
)


class OfficialPageExtractorTests(unittest.TestCase):
    def test_decode_html_content_uses_http_charset(self):
        """HTTP 头声明的字符集优先于 HTML meta 使用。"""
        html = b'<meta charset="utf-8">\xd6\xd0\xb9\xfa'
        self.assertEqual(
            decode_html_content(html, 'gbk'),
            '<meta charset="utf-8">中国',
        )

    def test_decode_html_content_falls_back_to_utf8(self):
        """没有 HTTP 字符集和 meta 声明时回退 UTF-8。"""
        self.assertEqual(
            decode_html_content('广州市'.encode('utf-8')),
            '广州市',
        )

    def collect(self, html, extra_address_labels=()):
        """从测试页面收集通用地址证据。"""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            result = collect_official_page_data(page, extra_address_labels)
            browser.close()
        return result['address_evidence']

    def test_fetch_browser_page_accepts_attached_hidden_body(self):
        """页面主体已挂载但隐藏时仍视为导航成功。"""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.route(
                'https://example.test/',
                lambda route: route.fulfill(
                    status=200,
                    content_type='text/html',
                    body='<html><body style="display:none"></body></html>',
                ),
            )
            response = fetch_browser_page(page, 'https://example.test/')
            browser.close()
        self.assertEqual(response.status, 200)

    def test_fetch_browser_page_uses_api_response_after_navigation_error(self):
        """Chromium 协议协商失败时仍可解析同一官网返回的 HTML。"""
        page = Mock()
        api_response = Mock(url='https://example.test/page')
        browser_response = Mock(status=200)
        page.request.get.return_value = api_response
        page.goto.side_effect = [PlaywrightError('connection closed'), browser_response]

        response = fetch_browser_page(page, 'https://example.test/page')

        self.assertIs(response, browser_response)
        page.request.get.assert_called_once_with(
            'https://example.test/page', timeout=40000,
            headers=unittest.mock.ANY,
        )
        page.route.assert_called_once()

    def test_fetch_browser_page_uses_api_response_after_repeated_timeout(self):
        page = Mock()
        api_response = Mock(url='https://example.test/page')
        browser_response = Mock(status=200)
        page.request.get.return_value = api_response
        page.goto.side_effect = [
            PlaywrightTimeoutError('timeout'),
            PlaywrightTimeoutError('timeout'),
            browser_response,
        ]

        response = fetch_browser_page(page, 'https://example.test/page')

        self.assertIs(response, browser_response)
        self.assertEqual(page.goto.call_count, 3)
        page.request.get.assert_called_once()

    @patch('query_city_core.web.fetch_official_page.collect_official_page_data')
    @patch('query_city_core.web.fetch_official_page.fetch_browser_page')
    @patch('query_city_core.web.fetch_official_page.sync_playwright')
    def test_fetcher_reuses_browser_and_isolates_each_page(
            self, playwright_factory, fetch_page, collect_data):
        playwright = playwright_factory.return_value.start.return_value
        browser = playwright.chromium.launch.return_value
        contexts = [Mock(), Mock()]
        pages = [context.new_page.return_value for context in contexts]
        for page in pages:
            page.url = 'https://example.edu.cn/'
            page.title.return_value = '示例大学'
        browser.new_context.side_effect = contexts
        fetch_page.return_value.status = 200
        collect_data.return_value = {'address_evidence': [], 'links': []}

        with OfficialPageFetcher() as fetcher:
            fetcher.fetch('https://example.edu.cn/', ['example.edu.cn'])
            fetcher.fetch('https://example.edu.cn/contact', ['example.edu.cn'])

        playwright.chromium.launch.assert_called_once_with(
            channel='chrome', headless=True, args=unittest.mock.ANY,
        )
        self.assertEqual(browser.new_context.call_count, 2)
        for context in contexts:
            context.close.assert_called_once_with()
        browser.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()

    @patch('query_city_core.web.fetch_official_page.collect_official_page_data')
    @patch('query_city_core.web.fetch_official_page.fetch_browser_page')
    @patch('query_city_core.web.fetch_official_page.sync_playwright')
    def test_fetch_pages_reuses_one_context_and_page_per_school(
            self, playwright_factory, fetch_page, collect_data):
        playwright = playwright_factory.return_value.start.return_value
        browser = playwright.chromium.launch.return_value
        context = Mock()
        page = context.new_page.return_value
        page.url = 'https://example.edu.cn/'
        page.title.return_value = '示例大学'
        browser.new_context.return_value = context
        fetch_page.return_value.status = 200
        collect_data.return_value = {'address_evidence': [], 'links': []}

        with OfficialPageFetcher() as fetcher:
            results = fetcher.fetch_pages([
                {'url': 'https://example.edu.cn/',
                 'official_domains': ['example.edu.cn']},
                {'url': 'https://example.edu.cn/contact',
                 'official_domains': ['example.edu.cn']},
            ])

        self.assertEqual(len(results), 2)
        kwargs = browser.new_context.call_args.kwargs
        self.assertIn('user_agent', kwargs)
        self.assertIn('extra_http_headers', kwargs)
        self.assertEqual(kwargs['locale'], 'zh-CN')
        self.assertEqual(kwargs['timezone_id'], 'Asia/Shanghai')
        context.new_page.assert_called_once_with()
        context.close.assert_called_once_with()

    @patch('query_city_core.web.fetch_official_page.collect_official_page_data')
    @patch('query_city_core.web.fetch_official_page.fetch_http_page')
    @patch('query_city_core.web.fetch_official_page.fetch_browser_page')
    @patch('query_city_core.web.fetch_official_page.sync_playwright')
    def test_fetcher_records_http_fallback_after_browser_failure(
            self, playwright_factory, fetch_page, fetch_http, collect_data):
        """浏览器失败后使用直连页面并保留两次访问审计。"""
        playwright = playwright_factory.return_value.start.return_value
        browser = playwright.chromium.launch.return_value
        context = Mock()
        page = context.new_page.return_value
        page.url = 'https://example.edu.cn/'
        page.title.return_value = '示例大学'
        browser.new_context.return_value = context
        fetch_page.side_effect = PlaywrightError('connection closed')
        fetch_http.return_value = type('Response', (), {
            'status': 200, 'url': 'https://example.edu.cn/'
        })()
        collect_data.return_value = {'address_evidence': [], 'links': []}

        with OfficialPageFetcher() as fetcher:
            result = fetcher.fetch('https://example.edu.cn/', ['example.edu.cn'])

        self.assertEqual(result['page_status'], 'ok')
        self.assertEqual([item['method'] for item in result['access_attempts']],
                         ['playwright', 'urllib_or_curl'])
        self.assertFalse(result['access_attempts'][0]['success'])
        self.assertTrue(result['access_attempts'][1]['success'])

    @patch('query_city_core.web.fetch_official_page.OfficialPageFetcher')
    def test_single_page_api_keeps_compatibility(self, fetcher_class):
        fetcher = fetcher_class.return_value.__enter__.return_value
        fetcher.fetch.return_value = {'page_status': 'ok'}

        result = fetch_official_page(
            'https://example.edu.cn/', ['example.edu.cn'],
            extra_address_labels=('校址',),
        )

        self.assertEqual(result, {'page_status': 'ok'})
        fetcher.fetch.assert_called_once_with(
            'https://example.edu.cn/', ['example.edu.cn'],
            extra_address_labels=('校址',),
        )

    def test_extracts_json_ld_postal_address(self):
        nodes = self.collect(
            '<script type="application/ld+json">'
            '{"@type":"Organization","address":{"@type":"PostalAddress",'
            '"addressRegion":"广东省","addressLocality":"深圳市",'
            '"streetAddress":"南山区科研路1号","postalCode":"518000"}}'
            '</script>'
        )
        self.assertEqual(nodes[0]['address_text'], '广东省深圳市南山区科研路1号')
        self.assertEqual(nodes[0]['extraction_method'], 'structured_data')

    def test_extracts_separate_label_and_sibling_value(self):
        nodes = self.collect(
            '<footer><div><p>地址</p><p>广东省深圳市坪山区兰田路3002号</p>'
            '<p>联系电话：0755-23256054</p></div></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '广东省深圳市坪山区兰田路3002号')
        self.assertEqual(nodes[0]['extraction_method'], 'label_relation')

    def test_extracts_label_element_with_adjacent_text_node(self):
        """弹性布局拆行时应读取标签元素后的直接文本地址。"""
        nodes = self.collect(
            '<main><p style="display:flex"><span>大学城校区：</span> '
            '广州市番禺区大学城外环东路232号</p>'
            '<p style="display:flex"><span>三元里校区：</span> '
            '广州市白云区机场路12号</p></main>',
            ('校区',),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广州市番禺区大学城外环东路232号', '广州市白云区机场路12号'],
        )
        self.assertTrue(all(item['extraction_method'] == 'label_relation' for item in nodes))

    def test_label_relation_does_not_merge_multiple_address_children(self):
        nodes = self.collect(
            '<footer><div>联系地址</div><div>'
            '<div><p>兰州新区校区：</p><p>兰州市兰州新区长江大道东段1942号</p></div>'
            '<div><p>七里河校区：</p><p>兰州市七里河区龚家坪东路1号</p></div>'
            '<div><p>联系电话：</p><p>0931-2861012</p></div>'
            '</div></footer>'
        )
        addresses = [item['address_text'] for item in nodes]
        self.assertIn('兰州市兰州新区长江大道东段1942号', addresses)
        self.assertIn('兰州市七里河区龚家坪东路1号', addresses)
        self.assertFalse(any('七里河校区： 兰州市' in item for item in addresses))

    def test_label_relation_rejects_multiline_navigation_container(self):
        nodes = self.collect(
            '<main><h2>南区网点</h2><nav>'
            '<a>首页</a><a>区域概况</a><a>服务指南</a><a>办事入口</a>'
            '</nav></main>',
            ('网点',),
        )
        self.assertEqual(nodes, [])

    def test_label_relation_uses_nested_inline_address_value(self):
        nodes = self.collect(
            '<dl><dt>云 塘 校 区</dt>'
            '<dd>地址：湖南省长沙市天心区万家丽南路二段960号</dd>'
            '<dd>邮编：410114</dd></dl>',
            ('校区',),
        )
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['address_text'], '湖南省长沙市天心区万家丽南路二段960号')
        self.assertEqual(nodes[0]['label_text'], '云 塘 校 区')

    def test_nested_specific_address_label_wins_over_generic_outer_label(self):
        nodes = self.collect(
            '<footer><p>学校地址</p>'
            '<p>昆仑校区地址：广西南宁市兴宁区昆仑大道8号</p></footer>',
            ('校区',),
        )
        self.assertEqual(nodes[0]['label_text'], '昆仑校区地址')

    def test_extracts_spaced_inline_label_and_stops_at_copyright(self):
        nodes = self.collect(
            '<footer><p>地 址：深圳市龙岗区创建路27号 版权所有©示例机构</p>'
            '<p>电话：0755-12345678</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '深圳市龙岗区创建路27号')
        self.assertEqual(nodes[0]['extraction_method'], 'inline_label')

    def test_inline_address_stops_before_localized_icp_prefix(self):
        nodes = self.collect(
            '<footer><p>滨海校区：茂名市高地智慧城慧城三街8号粤ICP备20000181号</p></footer>',
            ('校区',),
        )
        self.assertEqual(nodes[0]['address_text'], '茂名市高地智慧城慧城三街8号')

    def test_phone_field_does_not_consume_final_address_number_marker(self):
        nodes = self.collect(
            '<footer><p>联系地址：广州市海珠区新港西路152号联系电话：020-61230200</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '广州市海珠区新港西路152号')

    def test_spaced_inline_label_is_not_overridden_by_postcode_colon(self):
        nodes = self.collect(
            '<div>地址 :厦门市翔安区翔安东路1995号 '
            '<span>邮编 ：361101</span></div>'
        )
        self.assertEqual(nodes[0]['address_text'], '厦门市翔安区翔安东路1995号')

    def test_extracts_unlabeled_address_from_confirmed_footer_contact_block(self):
        nodes = self.collect(
            '<footer><nav>人才招聘 联系我们</nav>'
            '<span>广东省深圳市南山区学苑大道1088号</span>'
            '<span>电话：+86-755-88010114</span><span>邮编：518055</span></footer>'
        )
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['address_text'], '广东省深圳市南山区学苑大道1088号')
        self.assertEqual(nodes[0]['extraction_method'], 'footer_contact')

    def test_extracts_unlabeled_administrative_chain_from_footer_contact_block(self):
        nodes = self.collect(
            '<footer><p>四川省阿坝州汶川县水磨镇 | 值班室电话：0837-6241765</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '四川省阿坝州汶川县水磨镇')
        self.assertEqual(nodes[0]['extraction_method'], 'footer_contact')

    def test_rejects_multiline_government_link_list_as_administrative_chain(self):
        nodes = self.collect(
            '<div class="footer"><div>中华人民共和国教育部<br>'
            '山东省教育厅<br>山东省卫生健康委员会<br>山东省中医药管理局</div>'
            '<p>电话：0531-12345678</p></div>'
        )
        self.assertEqual(nodes, [])

    def test_unlabeled_footer_address_stops_at_switchboard_field(self):
        nodes = self.collect(
            '<footer><p>哈尔滨市南岗区西大直街92号 '
            '查号台：+86-451-86412114 P.C.:150001 Copyright © 示例大学</p>'
            '<p>电话：0451-12345678</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '哈尔滨市南岗区西大直街92号')

    def test_extracts_standalone_address_with_configured_parenthetical_suffix(self):
        nodes = self.collect(
            '<main><p>广东省广州市海珠区仑头路21号 510320(广州校区)</p></main>',
            ('校区',),
        )
        self.assertEqual(nodes[0]['address_text'], '广东省广州市海珠区仑头路21号 510320(广州校区)')
        self.assertEqual(nodes[0]['extraction_method'], 'configured_suffix')

    def test_configured_suffix_does_not_extract_news_sentence(self):
        nodes = self.collect(
            '<main><p>会议将在广东省广州市海珠区仑头路21号举行（广州校区）。</p></main>',
            ('校区',),
        )
        self.assertEqual(nodes, [])

    def test_inline_address_stops_at_admissions_phone_field(self):
        nodes = self.collect(
            '<footer><p>学校地址：重庆市黔江区武陵大道北段1785号 '
            '招生电话：023-79320888</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '重庆市黔江区武陵大道北段1785号')

    def test_inline_address_stops_at_hotline_phone_field(self):
        nodes = self.collect(
            '<footer><p>地址：晋中市榆次区龙湖东大街919号 '
            '热线电话：0354-2661839</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '晋中市榆次区龙湖东大街919号')

    def test_extracts_addresses_from_named_footer_location_block_without_contact(self):
        nodes = self.collect(
            '<div class="bottom"><div class="location">'
            '<div>示例大学南山校区(重庆市南岸区南山街道崇教路1号) 400065</div>'
            '<div>示例大学学府大道校区(重庆市南岸区学府大道9号) 400067</div>'
            '</div><p>版权©示例大学</p></div>'
        )
        self.assertEqual(len(nodes), 2)

    def test_rejects_unlabeled_body_address(self):
        nodes = self.collect('<main><p>广东省深圳市南山区学苑大道1088号</p></main>')
        self.assertEqual(nodes, [])

    def test_rejects_hidden_inline_address_in_body_news(self):
        nodes = self.collect(
            '<main><article style="display:none">采购人信息 名称：示例学校 '
            '地址：深圳市光明区公常路1号 联系方式：0755-88802424</article></main>'
        )
        self.assertEqual(nodes, [])

    def test_extracts_hidden_address_from_named_campus_panel(self):
        """非激活校区面板中有明确标题和地址标签时仍应提取。"""
        nodes = self.collect(
            '<main><section class="campus-tabs">'
            '<article><h4>广州校区南校园</h4>'
            '<p>通讯地址：广州市海珠区新港西路135号（510275）</p></article>'
            '<article style="display:none"><h4>广州校区北校园</h4>'
            '<p>通讯地址：广州市越秀区中山二路74号（510080）</p></article>'
            '<article style="display:none"><h4>广州校区东校园</h4>'
            '<p>通讯地址：广州市番禺区大学城外环东路132号（510006）</p></article>'
            '</section></main>',
            extra_address_labels=('校区', '校园'),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            [
                '广州市海珠区新港西路135号',
                '广州市越秀区中山二路74号',
                '广州市番禺区大学城外环东路132号',
            ],
        )

    def test_named_panel_uses_nested_address_leaf(self):
        """校区标题关联内容容器时，不应把相邻说明字段并入地址。"""
        nodes = self.collect(
            '<main><article style="display:none"><h4>珠海校区</h4>'
            '<div><div><p>通讯地址：珠海市香洲区唐家湾（519082）</p>'
            '<p>占地面积：3.571平方公里</p></div></div></article></main>',
            extra_address_labels=('校区', '校园'),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['珠海市香洲区唐家湾'],
        )

    def test_does_not_treat_next_campus_label_as_address(self):
        """相邻的另一个校区标题不是地址值。"""
        nodes = self.collect(
            '<main><h4>珠海校区</h4><h4>深圳校区</h4></main>',
            extra_address_labels=('校区', '校园'),
        )
        self.assertEqual(nodes, [])

    def test_rejects_hidden_body_label_relation(self):
        nodes = self.collect(
            '<main style="display:none"><p>东陆校区</p>'
            '<div>活动时间：6月11日 呈贡校区报告厅</div></main>',
            ('校区',),
        )
        self.assertEqual(nodes, [])

    def test_rejects_long_inline_address_in_visible_body_news(self):
        nodes = self.collect(
            '<main><article>采购项目公告' + '项目情况说明' * 30
            + ' 采购人地址：深圳市光明区公常路1号 联系方式：0755-88802424'
            + '</article></main>'
        )
        self.assertEqual(nodes, [])

    def test_hidden_inline_address_in_footer_is_preserved(self):
        nodes = self.collect(
            '<footer style="display:none"><p>地址：河北省邢台市威县开放东路</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '河北省邢台市威县开放东路')

    def test_common_bot_class_is_classified_as_footer_like(self):
        nodes = self.collect(
            '<div class="bot"><p>地址：广州市天河区迎福路527号</p></div>'
        )
        self.assertEqual(nodes[0]['source_region'], 'footer_like')

    def test_rejects_unconfirmed_footer_address(self):
        nodes = self.collect('<footer><p>广东省深圳市南山区学苑大道1088号</p></footer>')
        self.assertEqual(nodes, [])

    def test_rejects_footer_telephone_and_site_registration_numbers(self):
        nodes = self.collect(
            '<footer><p>+86(区号)95566</p><p>电话：010-12345678</p>'
            '<p>主办：示例市人民政府办公厅 网站标识码4403000016</p>'
            '<p>粤ICP备05017767号</p></footer>'
        )
        self.assertEqual(nodes, [])

    def test_explicit_label_accepts_address_without_road_or_number(self):
        nodes = self.collect('<footer><p>地址：江西省南昌市安义凤凰开发区</p></footer>')
        self.assertEqual(nodes[0]['address_text'], '江西省南昌市安义凤凰开发区')
        self.assertEqual(nodes[0]['evidence_strength'], 'strong')

    def test_rejects_truncated_labeled_address(self):
        nodes = self.collect('<main><p>通讯地址：广州市海珠区宝岗光...</p></main>')
        self.assertEqual(nodes, [])

    def test_inline_address_label_after_description_is_recognized(self):
        """长句描述后的“通讯地址：”标签应被识别并提取地址。"""
        nodes = self.collect(
            '<main><p>广东药科大学广州校区宝岗校园位于广州市海珠区，'
            '临床医学院设立在该校园并设有直属门诊部等。'
            '通讯地址：广州市海珠区宝岗光汉直街40号</p></main>'
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广州市海珠区宝岗光汉直街40号'],
        )
        self.assertEqual(nodes[0]['label_text'], '通讯地址')

    def test_campus_address_is_sentence_labels_are_recognized(self):
        """“东校区地址是…”一类标签句应被识别并逐校区提取。"""
        nodes = self.collect(
            '<main><p>学校现有五个校区。'
            '东校区地址是广州市天河区中山大道西293号。'
            '白云校区地址是广州市白云区江高镇环镇西路155号。</p></main>'
        )
        self.assertEqual(
            [(item['label_text'], item['address_text']) for item in nodes],
            [
                ('东校区地址', '广州市天河区中山大道西293号'),
                ('白云校区地址', '广州市白云区江高镇环镇西路155号'),
            ],
        )

    def test_address_keeps_previous_sibling_as_context(self):
        nodes = self.collect(
            '<footer><div><h3>第一地点</h3><h4>北京市朝阳区平乐园100号</h4></div>'
            '<p>电话：010-12345678</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '北京市朝阳区平乐园100号')
        self.assertEqual(nodes[0]['context_before'][0]['text'], '第一地点')
        self.assertEqual(nodes[0]['context_before'][0]['relation'], 'previous_sibling')

    def test_inline_label_removes_organization_prefix(self):
        nodes = self.collect(
            '<footer><p>示例机构 地址：云南省文山市学府路66号 邮编：663099</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '云南省文山市学府路66号')

    def test_category_specific_label_requires_extension(self):
        html = '<main><p>校址：北京市朝阳区平乐园100号</p></main>'
        self.assertEqual(self.collect(html), [])
        nodes = self.collect(html, ('校址',))
        self.assertEqual(nodes[0]['address_text'], '北京市朝阳区平乐园100号')

    def test_category_specific_label_accepts_configured_suffix(self):
        html = (
            '<footer><p>威海校区：山东省威海市乳山银滩AAAA旅游度假区</p>'
            '<p>济南校区：山东省济南市天桥区历山北路2号</p></footer>'
        )
        self.assertEqual(self.collect(html), [])
        nodes = self.collect(html, ('校区',))
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['山东省威海市乳山银滩AAAA旅游度假区', '山东省济南市天桥区历山北路2号'],
        )

    def test_configured_label_must_be_a_short_text_node(self):
        nodes = self.collect(
            '<main><section>' + '校园介绍' * 30
            + '<p>通讯地址：广州市海珠区江海大道283号</p>'
            + '<p>下一条：中山校区</p></section></main>'
            + '<footer><p>地址：广东省广州市大学城外环东路280号</p></footer>',
            ('校区',),
        )
        footer = next(
            item for item in nodes
            if item['address_text'] == '广东省广州市大学城外环东路280号'
        )
        self.assertEqual(footer['label_text'], '地址')

    def test_extracts_multiple_configured_labels_from_one_text_node(self):
        nodes = self.collect(
            '<footer><p>七渔河校区：阜阳市颍州区清河西路1066号 '
            '七渔河东校区：阜阳市颍州区清河西路259号 '
            '邮编：236031 联系电话：0558-2181325</p></footer>',
            ('校区',),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['阜阳市颍州区清河西路1066号', '阜阳市颍州区清河西路259号'],
        )

    def test_extracts_glued_address_fields_after_number_marker(self):
        nodes = self.collect(
            '<footer><p>天河校区：广州市天河区沙太南路113号'
            '清远校区：清远市清城区东城蟠龙园</p></footer>',
            ('校区',),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广州市天河区沙太南路113号', '清远市清城区东城蟠龙园'],
        )

    def test_extracts_repeated_address_is_fields(self):
        nodes = self.collect(
            '<main><p>广州天河校区地址为广州市天河区沙太南路113号，'
            '广州黄埔校区地址为广州市黄埔区江沥海街6号之一，'
            '清远校区地址为清远市清城区东城蟠龙园。</p></main>',
            ('校区',),
        )
        self.assertEqual(
            [(item['label_text'], item['address_text']) for item in nodes],
            [
                ('广州天河校区地址', '广州市天河区沙太南路113号'),
                ('广州黄埔校区地址', '广州市黄埔区江沥海街6号之一'),
                ('清远校区地址', '清远市清城区东城蟠龙园'),
            ],
        )

    def test_inline_address_keeps_continuation_from_adjacent_span(self):
        nodes = self.collect(
            '<main><p><span><span>东风路校区：广东省广州市越秀区东风东路</span>'
            '<span>729号；邮政编码：510090</span></span></p></main>',
            ('校区',),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广东省广州市越秀区东风东路729号'],
        )

    def test_richer_inline_address_replaces_truncated_label_relation(self):
        nodes = self.collect(
            '<main><p>学校地址：</p><p><span>'
            '<span>白云山校区：广东省广州市白云区白云大道北</span>'
            '<span>2号；邮政编码：510420</span></span></p></main>',
            ('校区',),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广东省广州市白云区白云大道北2号'],
        )

    def test_extracts_unlabeled_continuation_lines_in_footer_address_group(self):
        nodes = self.collect(
            '<footer><p>地址：贵州省遵义市新蒲新区校园1号路（新蒲校区）<br>'
            '遵义市汇川区大连路201号（大连路校区）<br>'
            '广东省珠海市金湾区金海岸（珠海校区）</p></footer>',
            ('校区',),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            [
                '贵州省遵义市新蒲新区校园1号路（新蒲校区）',
                '遵义市汇川区大连路201号（大连路校区）',
                '广东省珠海市金湾区金海岸（珠海校区）',
            ],
        )

    def test_source_newline_preserves_unlabeled_footer_address(self):
        nodes = self.collect(
            '<footer><p>地址：广州市从化江埔街环市东路767号\n'
            '邮编：510925\n广州天河区天寿路122号\n邮编：510635</p></footer>'
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广州市从化江埔街环市东路767号', '广州天河区天寿路122号'],
        )

    def test_confirmed_footer_splits_multiple_unlabeled_address_lines(self):
        nodes = self.collect(
            '<footer><div>广东省广州市番禺区市广路242号（主校区） '
            '邮编：511400<br>广东省广州市白云区同泰路1111号（白云校区） '
            '邮编：510515</div></footer>'
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            [
                '广东省广州市番禺区市广路242号（主校区）',
                '广东省广州市白云区同泰路1111号（白云校区）',
            ],
        )

    def test_configured_suffix_can_follow_address_in_sibling_span(self):
        nodes = self.collect(
            '<footer><p><span>广州市白云区广园中路511号</span>'
            '<span>邮编：510405（广园北校区）</span></p></footer>',
            ('校区',),
        )
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['address_text'], '广州市白云区广园中路511号')
        self.assertEqual(nodes[0]['label_text'], '广园北校区')

    def test_inline_address_stops_at_underscored_email_label(self):
        nodes = self.collect(
            '<footer><p>通讯地址:安徽省芜湖市乌霞山西路18号 '
            'E_MAIL:ahzyygzbgs@163.com</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '安徽省芜湖市乌霞山西路18号')

    def test_address_removes_terminal_template_empty_placeholders(self):
        nodes = self.collect(
            '<footer><p>昆仑校区地址:广西南宁市兴宁区昆仑大道8号'
            '<span>空空</span>邮编:530023</p>'
            '<p>桃源校区地址:广西南宁市青秀区桃源路37号'
            '<span>0空空</span>邮编:530021</p></footer>',
            ('校区',),
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广西南宁市兴宁区昆仑大道8号', '广西南宁市青秀区桃源路37号'],
        )

    def test_rejects_address_inside_local_report_section(self):
        nodes = self.collect(
            '<footer><div><p>学校地址</p><p>地址：广西南宁市兴宁区昆仑大道8号</p></div>'
            '<div><p>纪检举报</p><p>举报电话：0771-12388</p>'
            '<p>地址：昆仑校区笃学楼副楼3楼304室</p></div></footer>'
        )
        self.assertEqual(
            [item['address_text'] for item in nodes],
            ['广西南宁市兴宁区昆仑大道8号'],
        )

    def test_specific_school_address_label_survives_preceding_report_field(self):
        nodes = self.collect(
            '<footer><p><span>违法信息举报电话：0832-5908811</span>'
            '<span>学校地址：四川省隆昌市古湖街道人民中路六段368号</span></p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '四川省隆昌市古湖街道人民中路六段368号')

    def test_address_removes_leading_bullet_and_stops_at_sentence_end(self):
        nodes = self.collect(
            '<dl><dt>东校区</dt><dd>——广州市天河区中山大道西293号。'
            '（广州地铁11号线华景路站B1口）</dd></dl>',
            ('校区',),
        )
        self.assertEqual(nodes[0]['address_text'], '广州市天河区中山大道西293号')

    def test_address_removes_transport_note_but_keeps_campus_suffix(self):
        transport = self.collect(
            '<dl><dt>河源校区</dt><dd>河源市东源县东环路（长深高速东源出口）</dd></dl>',
            ('校区',),
        )
        campus = self.collect('<footer><p>地址：贵阳市花溪区大职路（花溪校区）</p></footer>')
        self.assertEqual(transport[0]['address_text'], '河源市东源县东环路')
        self.assertEqual(campus[0]['address_text'], '贵阳市花溪区大职路（花溪校区）')

    def test_address_removes_parenthesized_postcode(self):
        nodes = self.collect('<footer><p>地址：潍坊高新区胜利东街3031号（261061）</p></footer>')
        self.assertEqual(nodes[0]['address_text'], '潍坊高新区胜利东街3031号')

    def test_address_removes_opening_book_bracket_before_postcode(self):
        nodes = self.collect('<footer><p>地址：广州市增城区鹤泽路5号【邮编：511330】</p></footer>')
        self.assertEqual(nodes[0]['address_text'], '广州市增城区鹤泽路5号')

    def test_address_removes_open_parenthesis_before_postcode_field(self):
        nodes = self.collect('<footer><p>喀什校区：喀什市深喀大道666号（邮政编码：844000）</p></footer>', ('校区',))
        self.assertEqual(nodes[0]['address_text'], '喀什市深喀大道666号')

    def test_address_removes_trailing_landline(self):
        nodes = self.collect('<footer><p>地址：成都市安仁镇金山路188号 （028）88310888</p></footer>')
        self.assertEqual(nodes[0]['address_text'], '成都市安仁镇金山路188号')

    def test_address_removes_trailing_map_link_label(self):
        nodes = self.collect(
            '<footer><p>南校区：广州市白云区同和蟾蜍石东路2号'
            '<a href="/map">[交通图]</a></p></footer>',
            ('校区',),
        )
        self.assertEqual(nodes[0]['address_text'], '广州市白云区同和蟾蜍石东路2号')

    def test_address_removes_transport_guide_before_admission_phone(self):
        nodes = self.collect(
            '<footer><p>学校地址：襄阳市东津新区东津大道6号 '
            '<a href="/traffic">点击查看交通指引</a> '
            '招生咨询电话：0710-3622593</p></footer>'
        )
        self.assertEqual(nodes[0]['address_text'], '襄阳市东津新区东津大道6号')

    def test_footer_fallback_rejects_embedded_script_assignment(self):
        nodes = self.collect(
            '<footer><p>联系电话：0558-2181325</p>'
            '<div style="display:none">var ll_4697851 = 50; '
            '城乡建设学院（乡村振兴学院）</div></footer>'
        )
        self.assertEqual(nodes, [])

    def test_footer_fallback_rejects_unknown_labeled_destination(self):
        nodes = self.collect(
            '<footer><p>来信来访：乌鲁木齐市水磨沟区华瑞街777号纪检监察组201室</p>'
            '<p>电话：0991-1234567</p></footer>'
        )
        self.assertEqual(nodes, [])


if __name__ == '__main__':
    unittest.main()
