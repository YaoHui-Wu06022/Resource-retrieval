"""公共栏目页候选链接收集测试。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from query_city_core.directory_links import (
    DIRECTORY_LINK_MANIFEST_STAGE,
    collect_directory_links,
)


class CollectDirectoryLinksTests(unittest.TestCase):
    """验证栏目页链接抓取的链接模式与域名过滤。"""

    def write_input_manifest(self, source_dir: Path) -> Path:
        """写入一份栏目页清单并返回路径。"""
        input_path = source_dir / 'directory_manifest.json'
        input_path.write_text(
            json.dumps({
                'stage': DIRECTORY_LINK_MANIFEST_STAGE,
                'link_pattern': r'/content/post_\d+\.html$',
                'allowed_domain': 'www.example.gov.cn',
                'items': [{
                    'url': 'https://www.example.gov.cn/jyly/xx/index.html',
                    'note': '小学栏目',
                }],
            }, ensure_ascii=False),
            encoding='utf-8',
        )
        return input_path

    def test_directory_links_are_filtered_by_pattern_and_domain(self):
        """抓取结果应按链接模式和允许域名过滤并保留顺序。"""
        attempts = [{
            'method': 'urllib',
            'url': 'https://www.example.gov.cn/jyly/xx/index.html',
            'final_url': 'https://www.example.gov.cn/jyly/xx/index.html',
            'http_status': 200,
            'success': True,
            'error': '',
        }]
        html = (
            '<html><head><title>小学栏目</title></head><body>'
            '<a href="/jyly/xx/content/post_1.html">小学名录</a>'
            '<a href="/jyly/xx/content/post_2.html">九年一贯制名录</a>'
            '<a href="http://other.example.com/content/post_3.html">外站</a>'
            '<a href="/jyly/xx/notice.html">普通通知</a>'
            '</body></html>'
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            input_path = self.write_input_manifest(source_dir)
            output_path = source_dir / 'directory_links.json'
            with mock.patch(
                'query_city_core.directory_links.fetch_direct_content',
                return_value=(
                    html.encode('utf-8'),
                    'https://www.example.gov.cn/jyly/xx/index.html',
                    200,
                    attempts,
                    'utf-8',
                ),
            ):
                payload, exit_code = collect_directory_links(
                    input_path, output_path
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['metrics']['page_count'], 1)
            self.assertEqual(payload['metrics']['link_count'], 2)
            link_urls = [
                link['url'] for link in payload['items'][0]['links']
            ]
            self.assertEqual(link_urls, [
                'https://www.example.gov.cn/jyly/xx/content/post_1.html',
                'https://www.example.gov.cn/jyly/xx/content/post_2.html',
            ])
            self.assertEqual(
                payload['items'][0]['page_title'], '小学栏目'
            )

    def test_failed_directory_page_is_recorded_in_errors(self):
        """栏目页抓取失败应在输出 errors 中留痕。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            input_path = self.write_input_manifest(source_dir)
            output_path = source_dir / 'directory_links.json'
            with mock.patch(
                'query_city_core.directory_links.fetch_direct_content',
                side_effect=RuntimeError('连接失败'),
            ):
                payload, exit_code = collect_directory_links(
                    input_path, output_path
                )
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload['metrics']['error_count'], 1)
            self.assertEqual(payload['errors'][0]['error'], '连接失败')


if __name__ == '__main__':
    unittest.main()
