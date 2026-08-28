"""测试统一地址公共编排入口的来源路由。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from normalize_address import read_city_prefix_asset  # noqa: E402
from process_addresses import resolve_address_payload  # noqa: E402


def build_record(name, address, source):
    """构造一条公共地址输入记录。"""
    return {
        'place_name': name,
        'original_address': address,
        'source_nature': source,
        'source_reference': 'https://example.com/source',
        'attributes': {'名称': name},
    }


class ProcessAddressTests(unittest.TestCase):
    """覆盖网页检索和政府信息的地图调用边界。"""

    @classmethod
    def setUpClass(cls):
        """加载固定城市资产。"""
        cls.city_prefixes = read_city_prefix_asset()

    def run_payload(self, records):
        """使用可观测的地图替身执行公共链路。"""
        calls = []

        def verify(record, city, api_key, rate_limiter):
            """模拟地图验证并返回冲突状态。"""
            calls.append(('verify', record['place_name']))
            return {
                **record,
                'map_address': f'{city}地图验证地址1号',
                'map_status': 'conflict',
                'map_reason': '模拟冲突',
                'map_poi_type': '',
                'map_poi_typecode': '',
            }, 1

        def fallback(record, city, api_key, city_prefixes, rate_limiter):
            """模拟地图兜底并返回完整地址。"""
            calls.append(('fallback', record['place_name']))
            return {
                **record,
                'map_address': f'{city}天河区兜底路1号',
                'map_status': 'fallback',
                'map_reason': '模拟兜底',
                'map_poi_type': '测试类型',
                'map_poi_typecode': '000000',
            }, 1

        result = resolve_address_payload(
            {
                'stage': 'address_records',
                'city': '广州市',
                'items': records,
            },
            'test-key',
            self.city_prefixes,
            verify,
            fallback,
        )
        return result, calls

    def test_web_complete_is_verified_but_keeps_normalized_address(self):
        """网页完整地址即使地图冲突也采用规范地址。"""
        result, calls = self.run_payload([
            build_record('地点甲', '天河区黄埔大道西601号', 'web_search')
        ])
        record = result['items'][0]
        self.assertEqual(calls, [('verify', '地点甲')])
        self.assertEqual(record['map_status'], 'conflict')
        self.assertEqual(record['final_address'], '广州市天河区黄埔大道西601号')

    def test_web_empty_uses_fallback(self):
        """网页未取得地址时允许按地点名称兜底。"""
        result, calls = self.run_payload([
            build_record('地点乙', '', 'web_search')
        ])
        record = result['items'][0]
        self.assertEqual(calls, [('fallback', '地点乙')])
        self.assertEqual(record['final_address'], record['map_address'])

    def test_web_partial_does_not_use_map(self):
        """网页部分地址不得进入地图验证或兜底。"""
        result, calls = self.run_payload([
            build_record('地点丙', '天河区', 'web_search')
        ])
        self.assertEqual(calls, [])
        self.assertEqual(result['items'][0]['map_status'], 'skipped')
        self.assertEqual(result['items'][0]['final_address'], '')

    def test_government_complete_skips_map(self):
        """政府完整地址必须在地图调用前直接采用。"""
        result, calls = self.run_payload([
            build_record(
                '地点丁', '天河区黄埔大道西601号',
                'government_information',
            )
        ])
        record = result['items'][0]
        self.assertEqual(calls, [])
        self.assertEqual(record['map_status'], 'skipped')
        self.assertEqual(record['final_address'], record['normalized_address'])

    def test_government_empty_and_partial_use_fallback(self):
        """政府空地址和部分地址均允许地图兜底。"""
        result, calls = self.run_payload([
            build_record('地点戊', '', 'government_information'),
            build_record('地点己', '天河区', 'government_information'),
        ])
        self.assertEqual(
            calls,
            [('fallback', '地点戊'), ('fallback', '地点己')],
        )
        self.assertTrue(all(record['final_address'] for record in result['items']))

    def test_invalid_and_conflict_do_not_use_map(self):
        """两类来源的无效或跨城地址均不得兜底。"""
        result, calls = self.run_payload([
            build_record('地点庚', '地址： 电话：020', 'government_information'),
            build_record('地点辛', '深圳市南山区科技路1号', 'web_search'),
        ])
        self.assertEqual(calls, [])
        self.assertEqual(
            [record['normalization_status'] for record in result['items']],
            ['invalid', 'conflict'],
        )
        self.assertTrue(all(not record['final_address'] for record in result['items']))

    def test_order_attributes_and_no_ids_are_preserved(self):
        """公共处理保持输入顺序和业务字段且不生成标识字段。"""
        result, _ = self.run_payload([
            build_record('地点壬', '', 'web_search'),
            build_record('地点癸', '越秀区中山路1号', 'government_information'),
        ])
        self.assertEqual(
            [record['place_name'] for record in result['items']],
            ['地点壬', '地点癸'],
        )
        self.assertEqual(result['items'][0]['attributes'], {'名称': '地点壬'})
        self.assertTrue(all('id' not in record for record in result['items']))
        self.assertEqual(result['metrics']['map_request_count'], 1)


if __name__ == '__main__':
    unittest.main()
