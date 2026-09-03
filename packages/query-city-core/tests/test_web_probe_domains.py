"""通用官网域名探测能力测试。"""

import unittest

from query_city_core.web.probe_domains import (
    build_probe_item,
    probe_domain_items,
    title_matches_place_name,
)


class WebProbeDomainTests(unittest.TestCase):
    def test_title_matches_place_name(self):
        """标题含全名或去括号简称即视为身份匹配。"""
        self.assertTrue(title_matches_place_name('甲大学-官网', '甲大学'))
        self.assertTrue(title_matches_place_name('某科技大学', '某科技大学（广州）'))
        self.assertFalse(title_matches_place_name('Other Hospital', '乙医院'))

    def test_probe_item_flags_redirect_with_identity_match(self):
        """跳转到白名单外域名且身份匹配时给出迁移建议。"""

        def fake_fetch(url):
            return (
                '<title>乙医院</title>'.encode('utf-8'),
                'https://www.c.org.cn/',
                200,
                [],
                'utf-8',
            )

        item = build_probe_item(
            {
                'place_id': '1002',
                'place_name': '乙医院',
                'home_url': 'https://www.b.org.cn/',
                'official_domains': ['b.org.cn'],
            },
            fake_fetch,
        )
        self.assertTrue(item['reachable'])
        self.assertTrue(item['redirected'])
        self.assertFalse(item['final_domain_in_whitelist'])
        self.assertTrue(item['identity_match'])
        self.assertIn('c.org.cn', item['suggestion'])

    def test_probe_item_flags_unreachable(self):
        """访问失败时给出人工复核建议。"""

        def fake_fetch(url):
            raise RuntimeError('直连失败')

        item = build_probe_item(
            {
                'place_id': '1003',
                'place_name': '丙医院',
                'home_url': 'https://www.d.org.cn/',
                'official_domains': ['d.org.cn'],
            },
            fake_fetch,
        )
        self.assertFalse(item['reachable'])
        self.assertIn('访问失败', item['suggestion'])

    def test_probe_domain_items_keeps_generic_fields(self):
        """批量探测只使用 place_id/place_name 等通用字段。"""

        def fake_fetch(url):
            return (
                '<title>某医院</title>'.encode('utf-8'),
                url,
                200,
                [],
                'utf-8',
            )

        items = probe_domain_items(
            [
                {
                    'place_id': '1001',
                    'place_name': '某医院',
                    'home_url': 'https://www.a.org.cn/',
                    'official_domains': ['a.org.cn'],
                }
            ],
            fetch=fake_fetch,
        )
        self.assertEqual(items[0]['place_id'], '1001')
        self.assertEqual(items[0]['place_name'], '某医院')
        self.assertEqual(items[0]['final_domain'], 'www.a.org.cn')


if __name__ == '__main__':
    unittest.main()
