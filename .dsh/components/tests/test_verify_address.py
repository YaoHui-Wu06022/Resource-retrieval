"""测试规范地址与地图地理编码的交叉验证规则。"""

import sys
import unittest
from pathlib import Path


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from amap_client import RequestRateLimiter  # noqa: E402
from verify_address import (  # noqa: E402
    build_map_components,
    build_source_components,
    judge_address_match,
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
            '广州市',
            'test-key',
            RequestRateLimiter(0),
            fetch_geocodes,
        )
        self.assertEqual(request_count, 1)
        self.assertEqual(result['original_address'], record['original_address'])
        self.assertEqual(result['normalized_address'], record['normalized_address'])
        self.assertEqual(
            result['map_address'], '广东省广州市天河区黄埔大道西601号'
        )
        self.assertEqual(result['map_status'], 'consistent')


if __name__ == '__main__':
    unittest.main()
