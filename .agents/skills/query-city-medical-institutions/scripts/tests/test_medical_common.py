"""医疗机构公共拆分/去重逻辑测试。"""

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from medical_common import (  # noqa: E402
    build_medical_record,
    deduplicate_records,
    is_foreign_address_segment,
    split_address_segments,
)


def build_city_context():
    return {
        'stage': 'city_context',
        'input_city': '广州市',
        'city_name': '广州市',
        'province_name': '广东省',
        'subdivisions': [
            {'name': '越秀区', 'adcode': '440104', 'level': 'district'},
            {'name': '白云区', 'adcode': '440111', 'level': 'district'},
        ],
    }


class MedicalCommonTests(unittest.TestCase):
    def test_split_address_keeps_floor_fragment_with_previous_segment(self):
        segments = split_address_segments(
            '广州市越秀区府前路1号4号楼西215室，白云区远景路46号首层、'
            '二层，远景路72号301房'
        )
        self.assertEqual(segments, [
            '广州市越秀区府前路1号4号楼西215室',
            '白云区远景路46号首层、二层',
            '远景路72号301房',
        ])

    def test_foreign_segment_is_detected(self):
        context = build_city_context()
        self.assertTrue(is_foreign_address_segment(
            '南海平洲永安中路58号',
            context,
            ('南海平洲', '佛山市'),
        ))
        self.assertFalse(is_foreign_address_segment(
            '越秀区东川路91号',
            context,
            ('南海平洲', '佛山市'),
        ))

    def test_dedupe_keeps_multiple_addresses_of_same_license(self):
        context = build_city_context()
        records = [
            build_medical_record(
                's1', '某医院', '广州市越秀区中山二路106号', 1,
                'https://x | row 1 | 地址 1', context, '越秀区',
                license_no='1001',
            ),
            build_medical_record(
                's1', '某医院', '广州市越秀区惠福西路123号', 1,
                'https://x | row 1 | 地址 2', context, '越秀区',
                license_no='1001',
            ),
        ]
        self.assertEqual(len(deduplicate_records(records)), 2)

    def test_dedupe_merges_same_license_and_address(self):
        context = build_city_context()
        records = [
            build_medical_record(
                's1', '某医院', '广州市越秀区中山二路106号', 1,
                'https://a | row 1', context, '越秀区',
                license_no='1001',
            ),
            build_medical_record(
                's2', '某医院', '广州市越秀区中山二路106号', 1,
                'https://b | row 1', context, '越秀区',
                license_no='1001',
            ),
        ]
        self.assertEqual(len(deduplicate_records(records)), 1)


if __name__ == '__main__':
    unittest.main()
