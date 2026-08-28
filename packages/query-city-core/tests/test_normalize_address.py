"""测试统一地址记录的规范化规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from query_city_core.city import read_city_catalog  # noqa: E402
from query_city_core.address.normalize import (  # noqa: E402
    normalize_address_payload,
    normalize_address_text,
    normalize_address_value,
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


def build_city_context(city='广州市', province='广东省'):
    """构造地址批次使用的完整城市上下文。"""
    return {
        'stage': 'city_context',
        'input_city': city,
        'city_name': city,
        'province_name': province,
        'subdivisions': [],
    }


class NormalizeAddressTests(unittest.TestCase):
    """覆盖固定字段、状态定义和城市前缀规则。"""

    @classmethod
    def setUpClass(cls):
        """加载固定城市资产。"""
        cls.city_prefixes = read_city_catalog()

    def normalize(self, city, address):
        """规范化单个测试地址。"""
        return normalize_address_value(
            address,
            build_city_context(city, self.city_prefixes[city]),
        )

    def test_complete_address_adds_city_without_province(self):
        """完整地址只补城市且不输出省名。"""
        result = self.normalize('广州市', '广东省广州市天河区黄埔大道西601号')
        self.assertEqual(result['normalized_address'], '广州市天河区黄埔大道西601号')
        self.assertEqual(result['normalization_status'], 'complete')

    def test_country_and_repeated_admin_prefixes_are_removed(self):
        """国家、省市前缀不得重复进入规范地址。"""
        addresses = (
            '中国广东省广州市天河区广州大道中1268号',
            '中国广州市天河区广州大道中1268号',
        )
        for address in addresses:
            with self.subTest(address=address):
                result = self.normalize('广州市', address)
                self.assertEqual(
                    result['normalized_address'],
                    '广州市天河区广州大道中1268号',
                )
                self.assertEqual(result['normalization_status'], 'complete')

    def test_target_city_short_name_before_district_is_removed(self):
        """目标城市简称后接区县时按行政前缀处理。"""
        result = self.normalize('广州市', '广州天河区先烈东横路48号')
        self.assertEqual(
            result['normalized_address'],
            '广州市天河区先烈东横路48号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

    def test_other_city_short_name_after_province_short_name_conflicts(self):
        """省市简称明确指向目标城市外时标记冲突。"""
        result = self.normalize('广州市', '广东清远清城区中宿路27号')
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'conflict')

    def test_orphan_trailing_bracket_is_removed(self):
        """地址标签外层遗留的孤立右括号不得进入规范地址。"""
        result = self.normalize('广州市', '广州市花都区赤坭镇髻岭西路26号）')
        self.assertEqual(
            result['normalized_address'],
            '广州市花都区赤坭镇髻岭西路26号',
        )
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

    def test_missing_district_is_prefixed_from_record_unit(self):
        """缺少区县的地址应使用来源检索单元补齐。"""
        result = normalize_address_value(
            '广州市新港西路179号',
            build_city_context(),
            '海珠区',
        )
        self.assertEqual(result['normalized_address'], '广州市海珠区新港西路179号')
        self.assertEqual(result['normalization_status'], 'complete')

    def test_missing_district_without_record_unit_is_partial(self):
        """没有区县且无可信检索单元时不得生成完整地址。"""
        result = self.normalize('广州市', '新港西路179号')
        self.assertEqual(result['normalization_status'], 'partial')

    def test_functional_zone_does_not_replace_administrative_district(self):
        """开发区名称不能替代区县级行政区。"""
        result = normalize_address_value(
            '广州开发区开源大道11号',
            build_city_context(),
            '黄埔区',
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市黄埔区广州开发区开源大道11号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

    def test_location_zone_does_not_replace_administrative_district(self):
        """工业区和校区等具体位置前缀前仍应补充区县。"""
        result = normalize_address_value(
            '洛浦街桔树村万兴围工业区1号',
            build_city_context(),
            '番禺区',
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市番禺区洛浦街桔树村万兴围工业区1号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

    def test_other_district_conflicts_with_record_unit(self):
        """地址明确位于其他区县时不得归入当前检索单元。"""
        result = normalize_address_value(
            '天河区水荫一横路38号',
            build_city_context(),
            '越秀区',
        )
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'conflict')

    def test_campus_label_before_target_unit_is_removed(self):
        """校区标签和城市简称不能遮蔽后续可信区县。"""
        result = normalize_address_value(
            '南校区：广州市越秀区达道路1号',
            build_city_context(),
            '越秀区',
        )
        self.assertEqual(result['normalized_address'], '广州市越秀区达道路1号')
        self.assertEqual(result['normalization_status'], 'complete')

    def test_city_short_name_before_target_unit_is_removed(self):
        """省市简称前缀不能被误认为区县的一部分。"""
        result = normalize_address_value(
            '广东广州市白云区人和镇新和路33号',
            build_city_context(),
            '白云区',
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市白云区人和镇新和路33号',
        )

    def test_road_name_ending_with_flag_is_not_district(self):
        """八旗等道路名称片段不能被当作旗级行政区。"""
        result = normalize_address_value(
            '八旗二马路60号',
            build_city_context(),
            '越秀区',
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市越秀区八旗二马路60号',
        )

    def test_residential_zone_is_not_district(self):
        """商住区等具体地点不能被误认为区级行政单位。"""
        result = normalize_address_value(
            '晓港湾商住区英华街151号',
            build_city_context(),
            '海珠区',
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市海珠区晓港湾商住区英华街151号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

    def test_payload_uses_administrative_unit_attribute(self):
        """批处理应读取业务属性中的区县补全地址。"""
        record = build_record('市桥街西堤路136号')
        record['attributes']['administrative_unit'] = '番禺区'
        result = normalize_address_payload(
            {
                'stage': 'address_records',
                'city_context': build_city_context(),
                'items': [record],
            },
        )
        self.assertEqual(
            result['items'][0]['normalized_address'],
            '广州市番禺区市桥街西堤路136号',
        )

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
            '地址：广州市白云区太和兴太三路638号（510540） 电话：020-12345678'
        )
        self.assertEqual(cleaned, '广州市白云区太和兴太三路638号')

    def test_payload_preserves_order_and_attributes_without_ids(self):
        """批处理保持顺序和业务字段且不生成标识字段。"""
        payload = {
            'stage': 'address_records',
            'city_context': build_city_context(),
            'items': [
                build_record('天河区黄埔大道西601号', '地点甲'),
                build_record('', '地点乙'),
            ],
        }
        result = normalize_address_payload(payload)
        self.assertEqual(result['stage'], 'normalized_address_records')
        self.assertEqual(result['city_context'], build_city_context())
        self.assertEqual(
            [record['place_name'] for record in result['items']],
            ['地点甲', '地点乙'],
        )
        self.assertEqual(result['items'][0]['attributes'], {'业务名称': '地点甲'})
        self.assertNotIn('id', result['items'][0])

    def test_city_context_is_the_only_city_input(self):
        """地址模块不重新读取目录校验城市名称。"""
        result = normalize_address_value(
            '样本县示例路1号',
            build_city_context('示例市', '示例省'),
        )
        self.assertEqual(result['normalized_address'], '示例市样本县示例路1号')


if __name__ == '__main__':
    unittest.main()
