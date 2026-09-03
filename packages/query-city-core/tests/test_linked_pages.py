"""公共同构详情页批量保存测试。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from query_city_core.official.collectors.linked_pages import (
    collect_linked_html_pages,
)


class CollectLinkedHtmlPagesTests(unittest.TestCase):
    """验证名录页链接筛选、域名限制与失败留痕。"""

    def write_listing_html(
        self, source_dir: Path, links: str = ''
    ) -> Path:
        """写入一份名录页并返回路径。"""
        listing_path = source_dir / '名录.html'
        default_links = (
            '<a href="https://www.example.gov.cn/detail/1.html">名录</a>'
        )
        listing_path.write_text(
            '<html><body><div id="list">'
            f'{links or default_links}'
            '</div></body></html>',
            encoding='utf-8',
        )
        return listing_path

    def test_linked_pages_are_filtered_by_allowed_domain(self):
        """同域名链接被保存，跳转外站的链接被过滤。"""
        attempts = [{
            'method': 'urllib',
            'url': 'https://www.example.gov.cn/detail/1.html',
            'final_url': 'https://www.example.gov.cn/detail/1.html',
            'http_status': 200,
            'success': True,
            'error': '',
        }]
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            output_dir = source_dir / '详情页'
            listing_path = self.write_listing_html(
                source_dir,
                '<a href="https://www.example.gov.cn/detail/1.html">名录1</a>'
                '<a href="https://other.example.com/detail/2.html">外站</a>',
            )
            manifest_path = source_dir / '详情页清单.json'
            with mock.patch(
                'query_city_core.official.collectors.linked_pages.fetch_direct_content',
                return_value=(
                    '<html>详情</html>'.encode('utf-8'),
                    'https://www.example.gov.cn/detail/1.html',
                    200,
                    attempts,
                    'utf-8',
                ),
            ) as mocked_fetch:
                payload, exit_code = collect_linked_html_pages(
                    listing_path,
                    '#list a',
                    output_dir,
                    manifest_path,
                    'www.example.gov.cn',
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['metrics']['link_count'], 1)
            self.assertEqual(payload['metrics']['downloaded_count'], 1)
            mocked_fetch.assert_called_once()
            self.assertTrue((output_dir / '1.html').is_file())
            self.assertEqual(payload['items'][0]['local_file'], '详情页/1.html')

    def test_failed_detail_page_is_recorded_in_errors(self):
        """详情页下载失败应在清单 errors 中留痕。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            output_dir = source_dir / '详情页'
            listing_path = self.write_listing_html(source_dir)
            manifest_path = source_dir / '详情页清单.json'
            with mock.patch(
                'query_city_core.official.collectors.linked_pages.fetch_direct_content',
                side_effect=RuntimeError('连接失败'),
            ):
                payload, exit_code = collect_linked_html_pages(
                    listing_path, '#list a', output_dir, manifest_path
                )
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload['metrics']['error_count'], 1)
            self.assertEqual(payload['errors'][0]['error'], '连接失败')

    def test_no_qualified_links_raise_error(self):
        """没有合格详情页链接时应直接报错。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            listing_path = self.write_listing_html(
                source_dir,
                '<a href="mailto:test@example.gov.cn">邮箱</a>',
            )
            with self.assertRaisesRegex(ValueError, '没有找到合格'):
                collect_linked_html_pages(
                    listing_path,
                    '#list a',
                    source_dir / '详情页',
                    source_dir / '清单.json',
                )


if __name__ == '__main__':
    unittest.main()
