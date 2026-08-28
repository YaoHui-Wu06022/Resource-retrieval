"""测试公共城市名称标准化规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from normalize_city import (  # noqa: E402
    build_normalized_city_payload,
    normalize_city_name,
    read_city_prefix_asset,
)


class NormalizeCityTests(unittest.TestCase):
    """覆盖标准名称、补市规则和错误边界。"""

    @classmethod
    def setUpClass(cls):
        """加载固定城市资产。"""
        cls.city_prefixes = read_city_prefix_asset()

    def test_standard_city_name_is_unchanged(self):
        """固定资产中的标准名称直接返回。"""
        self.assertEqual(
            normalize_city_name('广州市', self.city_prefixes),
            '广州市',
        )

    def test_city_suffix_is_added_once(self):
        """普通城市简称仅补充一个市字。"""
        self.assertEqual(
            normalize_city_name(' 广州 ', self.city_prefixes),
            '广州市',
        )

    def test_municipality_suffix_is_added_once(self):
        """直辖市简称使用同一补市规则。"""
        self.assertEqual(
            normalize_city_name('北京', self.city_prefixes),
            '北京市',
        )

    def test_full_autonomous_prefecture_name_is_accepted(self):
        """自治州使用固定资产中的完整标准名称。"""
        city = '恩施土家族苗族自治州'
        self.assertEqual(
            normalize_city_name(city, self.city_prefixes),
            city,
        )

    def test_autonomous_prefecture_abbreviation_is_rejected(self):
        """公共层不对自治州简称进行模糊推断。"""
        with self.assertRaises(ValueError):
            normalize_city_name('恩施', self.city_prefixes)

    def test_unknown_city_is_rejected(self):
        """固定资产外的名称不得静默通过。"""
        with self.assertRaises(ValueError):
            normalize_city_name('示例市', self.city_prefixes)

    def test_empty_city_is_rejected(self):
        """空城市输入必须明确报错。"""
        with self.assertRaises(ValueError):
            normalize_city_name('  ', self.city_prefixes)

    def test_payload_keeps_input_and_standard_city(self):
        """公共结果同时保留清理后的输入和标准名称。"""
        subdivisions = [
            {'name': '越秀区', 'adcode': '440104', 'level': 'district'},
        ]
        result = build_normalized_city_payload(
            ' 广州 ', self.city_prefixes, subdivisions
        )
        self.assertEqual(result, {
            'schema_version': '1.1',
            'stage': 'normalized_city',
            'input_city': '广州',
            'city': '广州市',
            'subdivisions': subdivisions,
        })


if __name__ == '__main__':
    unittest.main()
