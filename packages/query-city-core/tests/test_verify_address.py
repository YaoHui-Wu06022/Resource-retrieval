"""测试规范地址与地图地理编码的交叉验证规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from query_city_core.amap_client import RequestRateLimiter  # noqa: E402
from query_city_core.address.verify import (  # noqa: E402
    build_map_components,
    build_source_components,
    judge_address_match,
    normalize_place_name,
    resolve_map_address,
    resolve_poi_address,
    select_poi_candidate,
    verify_map_address,
)


def build_record(detail, district='天河区'):
    """构造一条完整规范地址记录。"""
    return {
        'place_name': '测试地点',
        'original_address': f'{district}{detail}',
        'source_nature': 'web_search',
        'source_reference': 'https://example.com/source',
        'attributes': {},
        'normalized_address': f'广州市{district}{detail}',
        'normalization_status': 'complete',
        'normalization_reason': '',
    }


def judge_record(record, candidate):
    """构造双方组件并返回单条地址判定。"""
    source = build_source_components(record, '广州市')
    map_components = build_map_components(candidate, source)
    return judge_address_match(record['normalized_address'], source, map_components)


def build_candidate(address, district='天河区', street='', number=''):
    """构造一条高德地理编码候选。"""
    return {
        'formatted_address': address,
        'province': '广东省',
        'city': '广州市',
        'district': district,
        'street': street,
        'number': number,
    }


def build_city_context():
    """构造地图核验使用的城市上下文。"""
    return {
        'stage': 'city_context',
        'input_city': '广州市',
        'city_name': '广州市',
        'province_name': '广东省',
        'subdivisions': [],
    }


def build_poi(
    name,
    address,
    district='天河区',
    poi_type='科教文化服务;学校;高等院校',
):
    """构造高德 POI 返回记录。"""
    return {
        'name': name,
        'cityname': '广州市',
        'adname': district,
        'address': address,
        'type': poi_type,
        'typecode': '141201',
    }


class VerifyAddressTests(unittest.TestCase):
    """覆盖组件匹配和单条地图调用结果。"""

    def test_source_number_missing_from_map_is_partial(self):
        """官网有门牌号而地图缺门牌号时仅部分一致。"""
        record = build_record('黄埔大道西601号')
        candidate = build_candidate(
            '广东省广州市天河区黄埔大道西', street='黄埔大道西'
        )
        self.assertEqual(judge_record(record, candidate)[0], 'partial')

    def test_map_extra_number_is_consistent(self):
        """官网无门牌号而地图新增门牌号时不构成冲突。"""
        record = build_record('黄埔大道西')
        candidate = build_candidate(
            '广东省广州市天河区黄埔大道西601号',
            street='黄埔大道西',
            number='601号',
        )
        self.assertEqual(judge_record(record, candidate)[0], 'consistent')

    def test_different_house_number_is_conflict(self):
        """双方明确门牌号不同时判为冲突。"""
        record = build_record('黄埔大道西601号')
        candidate = build_candidate(
            '广东省广州市天河区黄埔大道西602号',
            street='黄埔大道西',
            number='602号',
        )
        self.assertEqual(judge_record(record, candidate)[0], 'conflict')

    def test_containment_alone_is_only_partial(self):
        """普通文本包含关系不能单独证明地址一致。"""
        record = build_record('某地点')
        candidate = build_candidate('广东省广州市天河区某地点东侧')
        self.assertEqual(judge_record(record, candidate)[0], 'partial')

    def test_park_anchor_is_consistent(self):
        """双方相同园区类锚点可以支持一致结论。"""
        record = build_record('增城职教园东行4千米', '增城区')
        candidate = build_candidate(
            '广东省广州市增城区朱村街道增城职教园', '增城区'
        )
        self.assertEqual(judge_record(record, candidate)[0], 'consistent')

    def test_named_place_anchor_is_consistent(self):
        """双方相同命名校区可以支持一致结论。"""
        record = build_record('石牌校区')
        candidate = build_candidate('广东省广州市天河区石牌校区')
        self.assertEqual(judge_record(record, candidate)[0], 'consistent')

    def test_other_city_is_conflict(self):
        """地图明确返回其他城市时判为冲突。"""
        record = build_record('黄埔大道西601号')
        candidate = build_candidate(
            '广东省佛山市禅城区黄埔大道西601号',
            district='禅城区',
            street='黄埔大道西',
            number='601号',
        )
        candidate['city'] = '佛山市'
        self.assertEqual(judge_record(record, candidate)[0], 'conflict')

    def test_verification_stores_map_address_without_overwriting_source(self):
        """地图验证单独保存地图地址并保持来源和规范地址。"""
        record = build_record('黄埔大道西')

        def fetch_geocodes(address, city, api_key, rate_limiter):
            """返回固定地理编码候选。"""
            return [build_candidate(
                '广东省广州市天河区黄埔大道西601号',
                street='黄埔大道西',
                number='601号',
            )], ''

        result, request_count = verify_map_address(
            record,
            build_city_context(),
            'test-key',
            RequestRateLimiter(0),
            fetch_geocodes,
        )
        self.assertEqual(request_count, 1)
        self.assertEqual(result['original_address'], record['original_address'])
        self.assertEqual(result['normalized_address'], record['normalized_address'])
        self.assertEqual(
            result['map_address'], '广州市天河区黄埔大道西601号'
        )
        self.assertEqual(result['map_status'], 'consistent')


class PoiAddressTests(unittest.TestCase):
    """覆盖 POI 返回记录的地点身份和地址筛选。"""

    city_context = build_city_context()

    def test_name_cleanup_ignores_brackets_and_connectors(self):
        """地点名称比较忽略无语义格式字符。"""
        self.assertEqual(
            normalize_place_name('暨南大学（番禺校区）'),
            normalize_place_name('暨南大学-番禺校区'),
        )

    def test_exact_cleaned_name_is_accepted(self):
        """清理后名称一致的 POI 可以提供地图地址。"""
        candidate, status, _ = select_poi_candidate(
            '暨南大学（番禺校区）',
            self.city_context,
            [build_poi('暨南大学-番禺校区', '兴业大道东855号', '番禺区')],
        )
        self.assertEqual(status, 'poi_match')
        self.assertEqual(candidate['map_address'], '广州市番禺区兴业大道东855号')

    def test_substring_name_is_rejected(self):
        """学校总名不得误匹配其附属单位或未指明的校区。"""
        candidate, status, _ = select_poi_candidate(
            '暨南大学',
            self.city_context,
            [
                build_poi('暨南大学番禺校区', '兴业大道东855号', '番禺区'),
                build_poi('暨南大学附属医院', '黄埔大道西601号'),
            ],
        )
        self.assertIsNone(candidate)
        self.assertEqual(status, 'not_found')

    def test_auxiliary_and_other_city_pois_are_rejected(self):
        """附属交通设施及目标城市外的 POI 不得作为地址结果。"""
        auxiliary = build_poi(
            '暨南大学',
            '黄埔大道西601号',
            poi_type='交通设施服务;公交车站;公交车站相关',
        )
        other_city = build_poi('暨南大学', '黄埔大道西601号')
        other_city['cityname'] = '深圳市'
        candidate, status, _ = select_poi_candidate(
            '暨南大学', self.city_context, [auxiliary, other_city]
        )
        self.assertIsNone(candidate)
        self.assertEqual(status, 'not_found')

    def test_administrative_unit_and_unique_address_are_required(self):
        """同名地点必须满足检索区县，且不能对应多个不同地址。"""
        wrong_unit, wrong_status, _ = select_poi_candidate(
            '金星小学',
            self.city_context,
            [build_poi('金星小学', '岐山大街4号', '白云区')],
            '番禺区',
        )
        ambiguous, ambiguous_status, _ = select_poi_candidate(
            '暨南大学',
            self.city_context,
            [
                build_poi('暨南大学', '黄埔大道西601号'),
                build_poi('暨南大学', '兴业大道东855号', '番禺区'),
            ],
        )
        self.assertIsNone(wrong_unit)
        self.assertEqual(wrong_status, 'not_found')
        self.assertIsNone(ambiguous)
        self.assertEqual(ambiguous_status, 'ambiguous')

    def test_missing_key_does_not_call_poi_fetch(self):
        """未配置密钥时不得发出 POI 请求。"""
        calls = []

        def fetch_pois(place_name, city, api_key, rate_limiter):
            calls.append((place_name, city))
            return [], ''

        result, request_count = resolve_poi_address(
            {'place_name': '暨南大学'},
            self.city_context,
            '',
            RequestRateLimiter(0),
            fetch_pois,
        )
        self.assertEqual(request_count, 0)
        self.assertEqual(calls, [])
        self.assertEqual(result['map_status'], 'error')


class MapResolutionTests(unittest.TestCase):
    """使用高德 fetch 返回记录测试统一地址解析的最终选择。"""

    def build_record(self, name, address, source, status=None):
        """构造已规范化的地址记录。"""
        return {
            'place_name': name,
            'original_address': address,
            'source_nature': source,
            'source_reference': 'https://example.com/source',
            'attributes': {},
            'normalized_address': address,
            'normalization_status': status or ('complete' if address else 'empty'),
            'normalization_reason': '',
        }

    def resolve(self, record, fetch_geocodes, fetch_pois):
        """将两个高德 fetch 替身的返回记录交给统一入口。"""
        return resolve_map_address(
            record,
            build_city_context(),
            'test-key',
            RequestRateLimiter(0),
            fetch_geocodes,
            fetch_pois,
        )

    def test_government_address_keeps_source_without_fetch(self):
        """政府资料已有道路地址时两个 fetch 均不得调用。"""
        record = self.build_record(
            '地点甲', '广州市天河区黄埔大道西601号', 'government_information'
        )

        def unexpected(*args):
            raise AssertionError(f'不应调用 fetch：{args}')

        result, request_count = self.resolve(record, unexpected, unexpected)
        self.assertEqual(request_count, 0)
        self.assertEqual(result['final_address'], record['normalized_address'])
        self.assertEqual(result['final_address_source'], 'official')

    def test_web_geocode_fetch_more_detailed_result_is_selected(self):
        """地理编码补足门牌号且无冲突时采用 fetch 返回的地图地址。"""
        record = self.build_record('地点乙', '广州市天河区黄埔大道西', 'web_search')

        def fetch_geocodes(*args):
            return [build_candidate(
                '广东省广州市天河区黄埔大道西601号',
                street='黄埔大道西',
                number='601号',
            )], ''

        def fetch_pois(*args):
            raise AssertionError('不应调用 POI fetch')

        result, request_count = self.resolve(record, fetch_geocodes, fetch_pois)
        self.assertEqual(request_count, 1)
        self.assertEqual(result['map_status'], 'consistent')
        self.assertEqual(result['final_address'], '广州市天河区黄埔大道西601号')
        self.assertEqual(result['final_address_source'], 'map')

    def test_web_geocode_fetch_conflict_keeps_official_address(self):
        """fetch 返回不同道路或门牌时保留官网地址。"""
        record = self.build_record('地点丙', '广州市天河区黄埔大道西601号', 'web_search')

        def fetch_geocodes(*args):
            return [build_candidate(
                '广东省广州市天河区五山路100号',
                street='五山路',
                number='100号',
            )], ''

        def fetch_pois(*args):
            raise AssertionError('不应调用 POI fetch')

        result, _ = self.resolve(record, fetch_geocodes, fetch_pois)
        self.assertEqual(result['map_status'], 'conflict')
        self.assertEqual(result['final_address'], record['normalized_address'])
        self.assertEqual(result['final_address_source'], 'official')

    def test_name_only_records_use_poi_fetch_result(self):
        """空地址或仅校区名称时使用唯一 POI fetch 返回地址。"""
        empty_record = self.build_record('地点丁', '', 'government_information')
        campus_record = self.build_record(
            '华南理工大学大学城校区',
            '广州市华南理工大学大学城校区',
            'web_search',
            'partial',
        )

        def fetch_geocodes(*args):
            raise AssertionError('不应调用地理编码 fetch')

        def fetch_pois(place_name, *args):
            if place_name == '地点丁':
                return [build_poi('地点丁', '黄埔大道西601号')], ''
            poi = build_poi('华南理工大学大学城校区', '大学城外环东路382号')
            poi['adname'] = '番禺区'
            return [poi], ''

        empty_result, empty_count = self.resolve(
            empty_record, fetch_geocodes, fetch_pois
        )
        campus_result, campus_count = self.resolve(
            campus_record, fetch_geocodes, fetch_pois
        )
        self.assertEqual(empty_count + campus_count, 2)
        self.assertEqual(empty_result['final_address_source'], 'map')
        self.assertEqual(
            campus_result['final_address'], '广州市番禺区大学城外环东路382号'
        )


if __name__ == '__main__':
    unittest.main()
