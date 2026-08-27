"""测试统一地址记录的规范化规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from normalize_address import (  # noqa: E402
    normalize_address_payload,
    normalize_address_text,
    normalize_address_value,
    read_city_prefix_asset,
)


def build_record(address, name='测试地点', source='web_search'):
    """构造一条最小公共地址输入记录。"""
    return {
        'place_name': name,
        'original_address': address,
        'source_nature': source,
        'source_reference': 'https://example.com/source',
        'attributes': {'业务名称': name},
    }


class NormalizeAddressTests(unittest.TestCase):
    """覆盖固定字段、状态定义和城市前缀规则。"""

    @classmethod
    def setUpClass(cls):
        """加载固定城市资产。"""
        cls.city_prefixes = read_city_prefix_asset()

    def normalize(self, city, address):
        """规范化单个测试地址。"""
        return normalize_address_value(address, city, self.city_prefixes)

    def test_complete_address_adds_city_without_province(self):
        """完整地址只补城市且不输出省名。"""
        result = self.normalize('广州市', '广东省广州市天河区黄埔大道西601号')
        self.assertEqual(result['normalized_address'], '广州市天河区黄埔大道西601号')
        self.assertEqual(result['normalization_status'], 'complete')

    def test_direct_municipality_keeps_city_and_district(self):
        """直辖市按市和区县正常输出。"""
        result = self.normalize('北京市', '海淀区颐和园路5号')
        self.assertEqual(result['normalized_address'], '北京市海淀区颐和园路5号')
        self.assertEqual(result['normalization_status'], 'complete')

    def test_empty_address_is_distinct_from_invalid(self):
        """原始空值固定标记为空地址。"""
        result = self.normalize('广州市', '')
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'empty')

    def test_cleaned_empty_address_is_invalid(self):
        """非空文本清理后无地址时标记为无效。"""
        result = self.normalize('广州市', '地址： 电话：020-12345678')
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'invalid')

    def test_admin_only_address_is_partial(self):
        """只有区县的地址标记为部分地址。"""
        result = self.normalize('广州市', '广东省广州市增城区')
        self.assertEqual(result['normalized_address'], '广州市增城区')
        self.assertEqual(result['normalization_status'], 'partial')

    def test_numbered_road_before_campus_name_is_complete(self):
        """道路门牌号后的校区名称不得使完整地址降级。"""
        result = self.normalize(
            '广州市',
            '荔湾区花地大道北320号广东实验中学荔湾学校花地湾校区',
        )
        self.assertEqual(result['normalization_status'], 'complete')

    def test_other_city_address_is_conflict(self):
        """明确指向其他城市的地址标记为冲突。"""
        result = self.normalize('广州市', '惠州市博罗县双龙大道1号')
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'conflict')

    def test_label_postcode_and_contact_are_removed(self):
        """地址标签、邮编和联系方式不进入规范地址。"""
        cleaned = normalize_address_text(
            '广州校区地址：广州市白云区太和兴太三路638号（510540） 电话：020-12345678'
        )
        self.assertEqual(cleaned, '广州市白云区太和兴太三路638号')

    def test_payload_preserves_order_and_attributes_without_ids(self):
        """批处理保持顺序和业务字段且不生成标识字段。"""
        payload = {
            'stage': 'address_records',
            'city': '广州市',
            'items': [
                build_record('天河区黄埔大道西601号', '地点甲'),
                build_record('', '地点乙'),
            ],
        }
        result = normalize_address_payload(payload, self.city_prefixes)
        self.assertEqual(result['stage'], 'normalized_address_records')
        self.assertEqual(
            [record['place_name'] for record in result['items']],
            ['地点甲', '地点乙'],
        )
        self.assertEqual(result['items'][0]['attributes'], {'业务名称': '地点甲'})
        self.assertNotIn('id', result['items'][0])

    def test_unknown_city_raises_error(self):
        """固定资产外的城市不得静默处理。"""
        with self.assertRaises(ValueError):
            self.normalize('示例市', '示例路1号')


if __name__ == '__main__':
    unittest.main()
