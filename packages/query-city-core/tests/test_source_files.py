"""公共来源文件批量下载测试。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from query_city_core.source_files import (
    SOURCE_DOWNLOAD_STAGE,
    download_source_files,
)


class DownloadSourceFilesTests(unittest.TestCase):
    """验证下载清单校验、文件保存与失败留痕。"""

    def build_manifest(self, source_dir: Path) -> Path:
        """写入一份最小下载清单并返回路径。"""
        manifest_path = source_dir / 'download_manifest.json'
        manifest_path.write_text(
            json.dumps({
                'stage': SOURCE_DOWNLOAD_STAGE,
                'items': [{
                    'file': '学校名录.html',
                    'url': 'https://www.example.gov.cn/list',
                }],
            }, ensure_ascii=False),
            encoding='utf-8',
        )
        return manifest_path

    def test_successful_download_writes_file_and_result(self):
        """成功下载应保存原始文件并把结果写回清单。"""
        attempts = [{
            'method': 'urllib',
            'url': 'https://www.example.gov.cn/list',
            'final_url': 'https://www.example.gov.cn/list',
            'http_status': 200,
            'success': True,
            'error': '',
        }]
        content = '<html>名录</html>'.encode('utf-8')
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            manifest_path = self.build_manifest(source_dir)
            with mock.patch(
                'query_city_core.source_files.fetch_direct_content',
                return_value=(
                    content,
                    'https://www.example.gov.cn/list',
                    200,
                    attempts,
                    'utf-8',
                ),
            ):
                manifest, exit_code = download_source_files(
                    manifest_path, source_dir
                )
            output_path = source_dir / '学校名录.html'
            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.is_file())
            self.assertEqual(output_path.read_bytes(), content)
            self.assertEqual(
                manifest['metrics']['downloaded_count'], 1
            )
            self.assertEqual(
                manifest['items'][0]['final_url'],
                'https://www.example.gov.cn/list',
            )
            self.assertEqual(manifest['items'][0]['http_status'], 200)
            self.assertEqual(
                manifest['items'][0]['access_attempts'], attempts
            )

    def test_failed_download_is_recorded_in_errors(self):
        """下载失败应在清单 errors 中留痕且不写文件。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            manifest_path = self.build_manifest(source_dir)
            with mock.patch(
                'query_city_core.source_files.fetch_direct_content',
                side_effect=RuntimeError('连接失败'),
            ):
                manifest, exit_code = download_source_files(
                    manifest_path, source_dir
                )
            self.assertEqual(exit_code, 1)
            self.assertEqual(manifest['metrics']['error_count'], 1)
            self.assertEqual(
                manifest['errors'][0]['error'], '连接失败'
            )
            self.assertFalse((source_dir / '学校名录.html').is_file())

    def test_output_file_name_must_stay_inside_directory(self):
        """输出文件名越出目标目录时应在写入前拒绝。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            manifest_path = self.build_manifest(source_dir)
            manifest_path.write_text(
                json.dumps({
                    'stage': SOURCE_DOWNLOAD_STAGE,
                    'items': [{
                        'file': '../escape.html',
                        'url': 'https://www.example.gov.cn/list',
                    }],
                }, ensure_ascii=False),
                encoding='utf-8',
            )
            with mock.patch(
                'query_city_core.source_files.fetch_direct_content'
            ) as mocked_fetch:
                with self.assertRaisesRegex(
                    ValueError, '越出目标目录'
                ):
                    download_source_files(manifest_path, source_dir)
                mocked_fetch.assert_not_called()

    def test_final_url_outside_allowed_domain_is_rejected(self):
        """下载结果跳到允许域名之外时按失败记录且不写文件。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            manifest_path = self.build_manifest(source_dir)
            manifest_path.write_text(
                json.dumps({
                    'stage': SOURCE_DOWNLOAD_STAGE,
                    'allowed_domain': 'www.example.gov.cn',
                    'items': [{
                        'file': '学校名录.html',
                        'url': 'https://www.example.gov.cn/list',
                    }],
                }, ensure_ascii=False),
                encoding='utf-8',
            )
            with mock.patch(
                'query_city_core.source_files.fetch_direct_content',
                return_value=(
                    '<html>名录</html>'.encode('utf-8'),
                    'https://other.example.com/redirect',
                    200,
                    [],
                    'utf-8',
                ),
            ):
                manifest, exit_code = download_source_files(
                    manifest_path, source_dir
                )
            self.assertEqual(exit_code, 1)
            self.assertEqual(manifest['metrics']['error_count'], 1)
            self.assertIn(
                '域名不在允许范围内', manifest['errors'][0]['error']
            )
            self.assertFalse((source_dir / '学校名录.html').is_file())


if __name__ == '__main__':
    unittest.main()
