"""测试公共地图地址兜底规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from amap_client import RequestRateLimiter  # noqa: E402
from fallback_address import (  # noqa: E402
    resolve_fallback_map_address,
    normalize_place_name,
    select_fallback_candidate,
)
from normalize_address import read_city_prefix_asset  # noqa: E402


def build_poi(
    name,
    address,
    district='天河区',
    poi_type='科教文化服务;学校;高等院校',
):
    """构造一条高德 POI 测试记录。"""
    return {
        'name': name,
        'cityname': '广州市',
        'adname': district,
        'address': address,
        'type': poi_type,
        'typecode': '141201',
    }


class FallbackAddressTests(unittest.TestCase):
    """覆盖严格名称、类型、城市和唯一地址规则。"""

    @classmethod
    def setUpClass(cls):
        """加载固定城市资产。"""
        cls.city_prefixes = read_city_prefix_asset()

    def test_name_cleanup_ignores_brackets_and_connectors(self):
        """名称比较只忽略无语义格式字符。"""
        self.assertEqual(
            normalize_place_name('暨南大学（番禺校区）'),
            normalize_place_name('暨南大学-番禺校区'),
        )

    def test_exact_cleaned_name_is_accepted(self):
        """清理后名称完全一致的候选可以接受。"""
        poi = build_poi('暨南大学-番禺校区', '兴业大道东855号', '番禺区')
        candidate, status, _ = select_fallback_candidate(
            '暨南大学（番禺校区）', '广州市', [poi], self.city_prefixes
        )
        self.assertEqual(status, 'fallback')
        self.assertEqual(candidate['map_address'], '广州市番禺区兴业大道东855号')

    def test_substring_name_is_rejected(self):
        """包含关系和附属单位名称均不得通过身份匹配。"""
        pois = [
            build_poi('暨南大学番禺校区', '兴业大道东855号', '番禺区'),
            build_poi('暨南大学附属医院', '黄埔大道西601号'),
        ]
        candidate, status, _ = select_fallback_candidate(
            '暨南大学', '广州市', pois, self.city_prefixes
        )
        self.assertIsNone(candidate)
        self.assertEqual(status, 'not_found')

    def test_auxiliary_poi_type_is_rejected(self):
        """同名公交站等明显附属设施不得作为兜底地址。"""
        poi = build_poi(
            '暨南大学',
            '黄埔大道西601号',
            poi_type='交通设施服务;公交车站;公交车站相关',
        )
        candidate, status, _ = select_fallback_candidate(
            '暨南大学', '广州市', [poi], self.city_prefixes
        )
        self.assertIsNone(candidate)
        self.assertEqual(status, 'not_found')

    def test_other_city_is_rejected(self):
        """地图返回城市与目标城市不同时不得接受。"""
        poi = build_poi('暨南大学', '黄埔大道西601号')
        poi['cityname'] = '深圳市'
        candidate, status, _ = select_fallback_candidate(
            '暨南大学', '广州市', [poi], self.city_prefixes
        )
        self.assertIsNone(candidate)
        self.assertEqual(status, 'not_found')

    def test_same_address_duplicates_are_deduplicated(self):
        """多个同名同址候选去重后仍可采用。"""
        pois = [
            build_poi('暨南大学', '黄埔大道西601号'),
            build_poi('暨南大学', '黄埔大道西601号'),
        ]
        candidate, status, _ = select_fallback_candidate(
            '暨南大学', '广州市', pois, self.city_prefixes
        )
        self.assertEqual(status, 'fallback')
        self.assertEqual(candidate['map_address'], '广州市天河区黄埔大道西601号')

    def test_distinct_addresses_are_ambiguous(self):
        """同名候选对应多个不同地址时不得选择。"""
        pois = [
            build_poi('暨南大学', '黄埔大道西601号'),
            build_poi('暨南大学', '兴业大道东855号', '番禺区'),
        ]
        candidate, status, _ = select_fallback_candidate(
            '暨南大学', '广州市', pois, self.city_prefixes
        )
        self.assertIsNone(candidate)
        self.assertEqual(status, 'ambiguous')

    def test_missing_key_does_not_issue_request(self):
        """未配置密钥时不得尝试地图请求。"""
        calls = []

        def fetch_pois(place_name, city, api_key, rate_limiter):
            """记录意外发出的地图请求。"""
            calls.append((place_name, city))
            return [], ''

        result, request_count = resolve_fallback_map_address(
            {'place_name': '暨南大学'},
            '广州市',
            '',
            self.city_prefixes,
            RequestRateLimiter(0),
            fetch_pois,
        )
        self.assertEqual(request_count, 0)
        self.assertEqual(calls, [])
        self.assertEqual(result['map_status'], 'error')


if __name__ == '__main__':
    unittest.main()
