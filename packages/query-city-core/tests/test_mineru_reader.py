"""测试 MinerU 页面解析客户端与结果转换。"""

import json
import unittest
from pathlib import Path
from unittest import mock

from query_city_core.official.readers.mineru_reader import (
    MineruClient,
    MineruConfigError,
    MineruError,
    build_vision_payload,
    content_list_table_rows,
    inspect_pdf_pages,
    sign_openxlab_nonce,
)


class MineruReaderTest(unittest.TestCase):
    """验证签名、鉴权缓存、结果转换与轮询逻辑。"""

    def test_sign_openxlab_nonce_hmac_sha256(self):
        """HMAC-SHA256 签名与 OpenXLab 约定一致。"""
        signature = sign_openxlab_nonce(
            'secret-key', 'hello-mineru', 'HmacSHA256'
        )
        self.assertEqual(
            signature,
            'uGRtz9jFLmyeEUDhyV7ElE+hSRdFgU/wDQHeJ/RaGmI=',
        )

    def test_client_requires_keys(self):
        """缺少 AK/SK 应给出配置错误。"""
        with self.assertRaises(MineruConfigError):
            MineruClient('', 'secret')
        with self.assertRaises(MineruConfigError):
            MineruClient('access', '')

    def test_jwt_exchange_and_cache(self):
        """auth→getJwt 换取 JWT，并缓存避免重复鉴权。"""
        client = MineruClient('ak', 'sk', auth_base='https://auth/')
        calls = []

        def fake_request(url, method='GET', payload=None, headers=None, timeout=60):
            calls.append((url, payload))
            if url.endswith('/auth'):
                return {
                    'msgCode': '10000',
                    'data': {
                        'msgCode': '10000',
                        'data': {
                            'nonce': 'n1',
                            'algorithm': 'HmacSHA256',
                        },
                    },
                }
            if url.endswith('/getJwt'):
                return {
                    'msgCode': '10000',
                    'data': {
                        'msgCode': '10000',
                        'data': {
                            'jwt': 'jwt-1',
                            'refresh_token': 'refresh-1',
                            'expiration': '2099-01-01 00:00:00',
                            'refresh_expiration': '2099-01-02 00:00:00',
                        },
                    },
                }
            raise AssertionError(f'unexpected url {url}')

        with mock.patch(
            'query_city_core.official.readers.mineru_reader._request_json',
            side_effect=fake_request,
        ):
            self.assertEqual(client.jwt(), 'jwt-1')
            self.assertEqual(client.jwt(), 'jwt-1')
        self.assertEqual(len(calls), 2)

    def test_content_list_table_rows_dedupes_header(self):
        """表块 HTML 应转成二维数组并去重复表头、还原中文标点。"""
        html = (
            '<table><tr><td>序号</td><td>单位</td></tr>'
            '<tr><td>1</td><td>广州市甲(小学),地址:乙路</td></tr></table>'
        )
        rows = content_list_table_rows(
            [{'type': 'table', 'table_body': html}]
        )
        self.assertEqual(rows, [
            ['序号', '单位'],
            ['1', '广州市甲（小学），地址：乙路'],
        ])

    def test_content_list_aligns_short_rows_with_missing_sequence(self):
        """缺序号列且首格为校名的短行应前插空单元格。"""
        html = (
            '<table><tr><td>序号</td><td>学校名称</td>'
            '<td>班数</td><td>电话</td></tr>'
            '<tr><td>85</td><td>九龙第二小学</td><td>6</td><td>1</td></tr>'
            '<tr><td>九龙第二小学（大坦校区）</td><td>1</td></tr>'
            '<tr><td>合计</td><td>413</td></tr></table>'
        )
        rows = content_list_table_rows(
            [{'type': 'table', 'table_body': html}]
        )
        self.assertEqual(rows[2], [
            '', '九龙第二小学（大坦校区）', '1', '',
        ])
        self.assertEqual(rows[3], ['', '合计', '413', ''])

    def test_content_list_keeps_single_cell_notes_and_aligns_campus_rows(self):
        """单格说明行不参与对齐；缺序号的校区行补空序号列。"""
        html = (
            '<table><tr><td>序号</td><td>学校</td><td>划片范围</td>'
            '<td>班数</td><td>电话</td></tr>'
            '<tr><td>22</td><td>主校</td><td>范围</td><td>6</td><td>1</td></tr>'
            '<tr><td>对口地段：甲路小学范围说明</td></tr>'
            '<tr><td>主校（智慧城校区）</td><td>10</td></tr>'
            '<tr><td>合计</td><td>288</td></tr></table>'
        )
        rows = content_list_table_rows(
            [{'type': 'table', 'table_body': html}]
        )
        self.assertEqual(
            rows[2], ['对口地段：甲路小学范围说明', '', '', '', '']
        )
        self.assertEqual(rows[3], ['', '主校（智慧城校区）', '10', '', ''])
        self.assertEqual(rows[4], ['', '合计', '288', '', ''])

    def test_build_vision_payload_skips_empty_pages(self):
        """组装 vision JSON 时按页排序且跳过空页。"""
        payload = build_vision_payload('名录.pdf.vision', {
            3: [['学校', '地址']],
            1: [['学校', '地址'], ['甲小学', '甲路1号']],
            2: [],
        })
        self.assertEqual(payload['stage'], 'vision_source_result')
        self.assertEqual(payload['source_file'], '名录.pdf.vision')
        self.assertEqual([page['page'] for page in payload['pages']], [1, 3])

    def test_wait_batch_returns_done_entries(self):
        """轮询直到所有页完成并按 data_id 返回。"""
        client = MineruClient('ak', 'sk')
        responses = [
            {'data': {'extract_result': [
                {'data_id': 'p0001', 'state': 'done', 'full_zip_url': 'u1'},
            ]}},
        ]

        def fake_request(url, method='GET', payload=None, headers=None, timeout=60):
            return responses.pop(0)

        with mock.patch(
            'query_city_core.official.readers.mineru_reader._request_json',
            side_effect=fake_request,
        ), mock.patch.object(
            client, 'poll_interval_seconds', 0
        ), mock.patch.object(
            client, '_authorized_headers', return_value={}
        ):
            result = client.wait_batch('batch-1', [1])
        self.assertEqual(result['p0001']['state'], 'done')

    def test_wait_batch_raises_on_failed(self):
        """任何一页解析失败都应整体报错。"""
        client = MineruClient('ak', 'sk')

        def fake_request(url, method='GET', payload=None, headers=None, timeout=60):
            return {'data': {'extract_result': [
                {'data_id': 'p0001', 'state': 'failed', 'err_msg': 'boom'},
            ]}}

        with mock.patch(
            'query_city_core.official.readers.mineru_reader._request_json',
            side_effect=fake_request,
        ), mock.patch.object(
            client, '_authorized_headers', return_value={}
        ):
            with self.assertRaises(MineruError):
                client.wait_batch('batch-1', [1])

    def test_inspect_pdf_pages_requires_credentials(self):
        """未配置 AK/SK 时检查命令给出配置错误。"""
        with mock.patch(
            'query_city_core.official.readers.mineru_reader.'
            'MineruClient.from_env',
            side_effect=MineruConfigError('missing'),
        ):
            with self.assertRaises(MineruConfigError):
                inspect_pdf_pages('https://example.com/a.pdf')


if __name__ == '__main__':
    unittest.main()
