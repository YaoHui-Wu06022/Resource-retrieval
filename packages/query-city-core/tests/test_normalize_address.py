"""测试统一地址记录的规范化规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from query_city_core.city import read_city_catalog  # noqa: E402
from query_city_core.address.normalize import (  # noqa: E402
    detect_city_prefix,
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


def build_city_context(city='广州市', province='广东省', subdivisions=None):
    """构造地址批次使用的完整城市上下文。"""
    return {
        'stage': 'city_context',
        'input_city': city,
        'city_name': city,
        'province_name': province,
        'subdivisions': subdivisions or [],
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

    def test_district_outside_city_subdivisions_conflicts(self):
        """区县不在目标城市下级行政区中时按异地排除。"""
        context = build_city_context(
            '广州市',
            '广东省',
            [
                {'name': '天河区', 'adcode': '440106', 'level': 'district'},
                {'name': '番禺区', 'adcode': '440113', 'level': 'district'},
            ],
        )
        result = normalize_address_value(
            '南山区科技园路1号',
            context,
        )
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'conflict')
        self.assertIn('不属于目标城市', result['normalization_reason'])

        county_result = normalize_address_value(
            '博罗县罗阳街道双龙大道1号',
            context,
        )
        self.assertEqual(county_result['normalization_status'], 'conflict')

    def test_district_inside_city_subdivisions_is_complete(self):
        """区县在目标城市下级行政区中时正常补城市名。"""
        context = build_city_context(
            '广州市',
            '广东省',
            [
                {'name': '天河区', 'adcode': '440106', 'level': 'district'},
                {'name': '番禺区', 'adcode': '440113', 'level': 'district'},
            ],
        )
        result = normalize_address_value(
            '天河区珠江新城华穗路1号',
            context,
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市天河区珠江新城华穗路1号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

    def test_street_only_without_district_stays_partial_for_map(self):
        """只有具体道路没有区县的地址保持部分状态交给地图补充。"""
        context = build_city_context(
            '广州市',
            '广东省',
            [
                {'name': '天河区', 'adcode': '440106', 'level': 'district'},
            ],
        )
        result = normalize_address_value(
            '黄埔大道西601号',
            context,
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市黄埔大道西601号',
        )
        self.assertEqual(result['normalization_status'], 'partial')
        self.assertEqual(result['normalization_reason'], '地址缺少下级行政区')

    def test_city_without_district_accepts_street_as_admin_unit(self):
        """不设区县的城市把街道或镇视为行政区层级。"""
        context = build_city_context(
            '东莞市',
            '广东省',
            [
                {'name': '南城街道', 'adcode': '441900004', 'level': 'street'},
                {'name': '长安镇', 'adcode': '441900109', 'level': 'street'},
            ],
        )
        result = normalize_address_value('南城街道宏图路1号', context)
        self.assertEqual(
            result['normalized_address'],
            '东莞市南城街道宏图路1号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

        town_result = normalize_address_value('长安镇霄边大街1号', context)
        self.assertEqual(
            town_result['normalized_address'],
            '东莞市长安镇霄边大街1号',
        )
        self.assertEqual(town_result['normalization_status'], 'complete')

    def test_city_without_district_missing_street_is_partial(self):
        """不设区县的城市缺少街道或镇时保持部分状态交给地图。"""
        context = build_city_context(
            '东莞市',
            '广东省',
            [{'name': '南城街道', 'adcode': '441900004', 'level': 'street'}],
        )
        street_only = normalize_address_value('南城街道', context)
        self.assertEqual(street_only['normalization_status'], 'partial')
        self.assertEqual(
            street_only['normalization_reason'],
            '地址缺少行政区之后的具体位置',
        )
        road_only = normalize_address_value('宏图路1号', context)
        self.assertEqual(road_only['normalization_status'], 'partial')
        self.assertEqual(road_only['normalization_reason'], '地址缺少下级行政区')

    def test_street_without_district_in_districted_city_is_partial(self):
        """有区县的城市出现街道漏写区县时保持部分状态交给地图。"""
        context = build_city_context(
            '广州市',
            '广东省',
            [{'name': '天河区', 'adcode': '440106', 'level': 'district'}],
        )
        result = normalize_address_value(
            '新港街道新港西路179号',
            context,
        )
        self.assertEqual(
            result['normalized_address'],
            '广州市新港街道新港西路179号',
        )
        self.assertEqual(result['normalization_status'], 'partial')
        self.assertEqual(result['normalization_reason'], '地址缺少下级行政区')

    def test_short_admin_name_matches_subdivision_prefix(self):
        """下级行政区简称按目录名称前缀匹配。"""
        context = build_city_context(
            '中山市',
            '广东省',
            [
                {'name': '西区街道', 'adcode': '442000005', 'level': 'street'},
                {'name': '石岐街道', 'adcode': '442000001', 'level': 'street'},
            ],
        )
        result = normalize_address_value('西区富华道1号', context)
        self.assertEqual(
            result['normalized_address'],
            '中山市西区富华道1号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

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

    def test_foreign_city_full_name_without_district_conflicts(self):
        """外地市全名即使没有区县也按城市归属排除。"""
        result = self.normalize('广州市', '深圳市科技园南路1号')
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'conflict')
        self.assertEqual(result['resolved_city'], '深圳市')

    def test_foreign_city_short_name_with_district_conflicts(self):
        """城市简称后接区县时按城市目录识别为异地。"""
        result = self.normalize('广州市', '深圳南山区科技园路1号')
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'conflict')
        self.assertEqual(result['resolved_city'], '深圳市')

    def test_municipality_short_name_with_district_conflicts(self):
        """直辖市简称后接区县时识别为异地。"""
        result = self.normalize('广州市', '上海浦东新区世纪大道1号')
        self.assertEqual(result['normalized_address'], '')
        self.assertEqual(result['normalization_status'], 'conflict')
        self.assertEqual(result['resolved_city'], '上海市')

    def test_foreign_city_campus_name_in_place_name_conflicts(self):
        """地点名称含异地城市校区时无需地址文本也按异地排除。"""
        record = build_record('', '广州软件学院江门校区')
        record['attributes'] = {'campus_name': '江门校区'}
        result = normalize_address_payload(
            {
                'stage': 'address_records',
                'city_context': build_city_context(),
                'items': [record],
            },
        )
        item = result['items'][0]
        self.assertEqual(item['normalized_address'], '')
        self.assertEqual(item['normalization_status'], 'conflict')
        self.assertEqual(item['resolved_city'], '江门市')
        self.assertIn('江门市', item['normalization_reason'])

    def test_target_city_address_overrides_foreign_campus_name(self):
        """官方地址能落到目标城市时，校区名中的异地简称不得判冲突。"""
        context = build_city_context(
            '广州市',
            '广东省',
            [{'name': '天河区', 'adcode': '440106', 'level': 'district'}],
        )
        record = build_record(
            '天河区东方二路1号', '广州市第一一三中学东方校区'
        )
        record['attributes'] = {
            'administrative_unit': '天河区',
            'campus_name': '东方校区',
        }
        result = normalize_address_payload(
            {
                'stage': 'address_records',
                'city_context': context,
                'items': [record],
            },
        )
        item = result['items'][0]
        self.assertEqual(
            item['normalized_address'], '广州市天河区东方二路1号'
        )
        self.assertEqual(item['normalization_status'], 'complete')
        self.assertEqual(item['resolved_city'], '广州市')
        self.assertNotIn('异地', item['normalization_reason'])

    def test_partial_target_city_address_overrides_foreign_campus_name(self):
        """只有目标区县的部分地址也不因校区名中的异地简称判冲突。"""
        context = build_city_context(
            '广州市',
            '广东省',
            [{'name': '天河区', 'adcode': '440106', 'level': 'district'}],
        )
        record = build_record('天河区', '示例学校东方校区')
        record['attributes'] = {
            'administrative_unit': '天河区',
            'campus_name': '东方校区',
        }
        result = normalize_address_payload(
            {
                'stage': 'address_records',
                'city_context': context,
                'items': [record],
            },
        )
        item = result['items'][0]
        self.assertEqual(item['normalized_address'], '广州市天河区')
        self.assertEqual(item['normalization_status'], 'partial')
        self.assertNotIn('异地', item['normalization_reason'])

    def test_target_city_campus_name_is_not_foreign(self):
        """目标城市校区名与校名中的城市简称不得误判为异地。"""
        record = build_record('', '中山大学广州校区')
        record['attributes'] = {'campus_name': '广州校区'}
        result = normalize_address_payload(
            {
                'stage': 'address_records',
                'city_context': build_city_context(),
                'items': [record],
            },
        )
        item = result['items'][0]
        self.assertEqual(item['normalization_status'], 'empty')
        self.assertNotIn('异地', item['normalization_reason'])

    def test_place_name_with_city_suffix_not_mistaken_for_foreign_city(self):
        """含地区、市场等城市后缀词的地点不得误判为异地城市。"""
        result = self.normalize('北京市', '朝阳区常营回族地区朝阳路1号')
        self.assertEqual(
            result['normalized_address'],
            '北京市朝阳区常营回族地区朝阳路1号',
        )
        self.assertEqual(result['normalization_status'], 'complete')

    def test_detect_city_prefix_strips_any_province(self):
        """外省前缀不应混入返回的城市名称。"""
        self.assertEqual(
            detect_city_prefix('湖北省武汉市武昌区珞珈山路1号'),
            '武汉市',
        )
        self.assertEqual(detect_city_prefix('深圳南山区科技园路1号'), '深圳市')

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
