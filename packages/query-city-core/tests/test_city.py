"""测试公共城市名称标准化规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from query_city_core.city import (  # noqa: E402
    build_city_context,
    normalize_city_name,
    read_city_catalog,
    resolve_city_context,
)


class CityTests(unittest.TestCase):
    """覆盖标准名称、补市规则和错误边界。"""

    @classmethod
    def setUpClass(cls):
        """加载固定城市资产。"""
        cls.city_catalog = read_city_catalog()

    def test_standard_city_name_is_unchanged(self):
        """固定资产中的标准名称直接返回。"""
        self.assertEqual(
            normalize_city_name('广州市', self.city_catalog),
            '广州市',
        )

    def test_city_suffix_is_added_once(self):
        """普通城市简称仅补充一个市字。"""
        self.assertEqual(
            normalize_city_name(' 广州 ', self.city_catalog),
            '广州市',
        )

    def test_municipality_suffix_is_added_once(self):
        """直辖市简称使用同一补市规则。"""
        self.assertEqual(
            normalize_city_name('北京', self.city_catalog),
            '北京市',
        )

    def test_full_autonomous_prefecture_name_is_accepted(self):
        """自治州使用固定资产中的完整标准名称。"""
        city = '恩施土家族苗族自治州'
        self.assertEqual(
            normalize_city_name(city, self.city_catalog),
            city,
        )

    def test_region_suffix_is_added_once(self):
        """地区名称可补充一个地区后缀。"""
        self.assertEqual(
            normalize_city_name('阿勒泰', self.city_catalog),
            '阿勒泰地区',
        )

    def test_unknown_city_is_rejected(self):
        """固定资产外的名称不得静默通过。"""
        with self.assertRaises(ValueError):
            normalize_city_name('示例市', self.city_catalog)

    def test_empty_city_is_rejected(self):
        """空城市输入必须明确报错。"""
        with self.assertRaises(ValueError):
            normalize_city_name('  ', self.city_catalog)

    def test_context_keeps_city_and_province(self):
        """城市上下文保留规范城市、上级和下级行政单位。"""
        subdivisions = [
            {'name': '越秀区', 'adcode': '440104', 'level': 'district'},
        ]
        result = build_city_context(
            ' 广州 ', self.city_catalog, subdivisions
        )
        self.assertEqual(result, {
            'stage': 'city_context',
            'input_city': '广州',
            'city_name': '广州市',
            'province_name': '广东省',
            'subdivisions': subdivisions,
        })

    def test_context_uses_high_de_after_offline_normalization(self):
        """高德查询只接收标准化后的城市名称。"""
        subdivisions = [{'name': '海淀区', 'adcode': '110108', 'level': 'district'}]

        def fetch_subdivisions(city_name, api_key, rate_limiter):
            self.assertEqual(city_name, '北京市')
            self.assertEqual(api_key, 'test-key')
            self.assertIsNotNone(rate_limiter)
            return subdivisions, ''

        result = resolve_city_context(
            '北京',
            'test-key',
            self.city_catalog,
            fetch_subdivisions,
        )
        self.assertEqual(result['city_name'], '北京市')
        self.assertIsNone(result['province_name'])
        self.assertEqual(result['subdivisions'], subdivisions)


if __name__ == '__main__':
    unittest.main()
