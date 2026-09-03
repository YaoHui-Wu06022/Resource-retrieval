"""测试高德公共客户端的行政区结果转换。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from query_city_core.address.amap_client import fetch_amap_subdivisions  # noqa: E402


class AmapClientTests(unittest.TestCase):
    """覆盖城市精确匹配和直接下级提取。"""

    @patch('query_city_core.address.amap_client.fetch_amap_payload')
    def test_fetches_only_direct_subdivisions(self, request_payload):
        """仅返回目标城市记录携带的直接下一级行政区。"""
        request_payload.return_value = ({
            'districts': [{
                'name': '广州市',
                'adcode': '440100',
                'level': 'city',
                'districts': [
                    {'name': '越秀区', 'adcode': '440104', 'level': 'district'},
                    {'name': '从化区', 'adcode': '440117', 'level': 'district'},
                    {'name': '示例镇', 'adcode': '440117', 'level': 'street'},
                ],
            }],
        }, '')

        subdivisions, error_reason = fetch_amap_subdivisions(
            '广州市', 'test-key', object()
        )

        self.assertEqual(error_reason, '')
        self.assertEqual(subdivisions, [
            {'name': '越秀区', 'adcode': '440104', 'level': 'district'},
            {'name': '从化区', 'adcode': '440117', 'level': 'district'},
            {'name': '示例镇', 'adcode': '440117', 'level': 'street'},
        ])

    @patch('query_city_core.address.amap_client.fetch_amap_payload')
    def test_rejects_ambiguous_city_match(self, request_payload):
        """目标城市无法唯一匹配时返回明确错误。"""
        request_payload.return_value = ({'districts': []}, '')

        subdivisions, error_reason = fetch_amap_subdivisions(
            '示例市', 'test-key', object()
        )

        self.assertEqual(subdivisions, [])
        self.assertIn('未唯一匹配', error_reason)

    @patch('query_city_core.address.amap_client.fetch_amap_payload')
    def test_unwraps_municipality_city_layer(self, request_payload):
        """自动展开直辖市在高德结果中的城区中间层。"""
        request_payload.side_effect = [
            ({'districts': [{
                'name': '北京市',
                'districts': [
                    {'name': '北京城区', 'adcode': '110100', 'level': 'city'},
                ],
            }]}, ''),
            ({'districts': [{
                'name': '北京城区',
                'districts': [
                    {'name': '东城区', 'adcode': '110101', 'level': 'district'},
                    {'name': '西城区', 'adcode': '110102', 'level': 'district'},
                ],
            }]}, ''),
        ]

        subdivisions, error_reason = fetch_amap_subdivisions(
            '北京市', 'test-key', object()
        )

        self.assertEqual(error_reason, '')
        self.assertEqual(
            [item['name'] for item in subdivisions],
            ['东城区', '西城区'],
        )


if __name__ == '__main__':
    unittest.main()
