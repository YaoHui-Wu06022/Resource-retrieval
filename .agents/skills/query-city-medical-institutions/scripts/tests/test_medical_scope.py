"""医疗机构城市级去重、物理区分桶与类别归并测试。"""

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from medical_scope import (  # noqa: E402
    classify_institution_category,
    merge_city_records,
    partition_main_records,
    resolve_effective_administrative_unit,
)


def build_record(
    place_name,
    original_address,
    final_address='',
    administrative_unit='甲区',
    license_no='',
    institution_type='普通诊所',
    institution_level='',
):
    """构造一条带属性与地址的处理记录。"""
    attributes = {
        'administrative_unit': administrative_unit,
        'license_administrative_unit': administrative_unit,
        'subdivision_scope': 'subdivision',
        'institution_type': institution_type,
        'institution_level': institution_level,
        'license_no': license_no,
    }
    return {
        'place_name': place_name,
        'original_address': original_address,
        'address_mode': 'government_list',
        'source_nature': 'government_information',
        'source_reference': 'https://example.gov/list | row 1',
        'attributes': attributes,
        'final_address': final_address or original_address,
        'map_match_status': 'skipped',
    }


class MedicalScopeTests(unittest.TestCase):
    def test_classify_institution_category_uses_major_buckets(self):
        """官方类型归并为医院/基层/门诊诊所/实验室/其他大类。"""
        examples = {
            '综合医院': '医院',
            '中医（综合）医院': '医院',
            '妇幼保健院': '其他',
            '社区卫生服务中心': '基层医疗卫生机构',
            '乡卫生院': '基层医疗卫生机构',
            '村卫生室': '基层医疗卫生机构',
            '卫生站': '基层医疗卫生机构',
            '卫生保健所': '基层医疗卫生机构',
            '医务室': '基层医疗卫生机构',
            '口腔门诊部': '门诊部与诊所',
            '普通诊所（备案）': '门诊部与诊所',
            '疾病预防控制中心': '其他',
            '职业病防治所（站、中心）': '其他',
            '急救中心（站）': '其他',
            '中心血站': '其他',
            '医学检验实验室': '医学检验机构',
            '临床检验中心': '医学检验机构',
            '血液透析中心': '其他',
            '护理院': '其他',
            '': '',
        }
        for raw_value, expected in examples.items():
            self.assertEqual(
                classify_institution_category(raw_value),
                expected,
                raw_value,
            )

    def test_merge_links_licensed_and_platform_records(self):
        """同一机构地址的带登记号与平台记录跨目录合并为一条。"""
        licensed = build_record(
            '某诊所',
            '示例市甲区测试路1号',
            license_no='1001',
            institution_type='诊所',
        )
        platform = build_record(
            '某诊所',
            '示例市甲区测试路1号',
            license_no='',
            institution_type='普通诊所（备案）',
        )
        merged = merge_city_records(
            [licensed, platform], ['甲区', '乙区']
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            (merged[0]['attributes'] or {}).get('license_no'),
            '1001',
        )

    def test_merge_keeps_multiple_addresses_of_same_license(self):
        """同一登记号的不同执业地址在物理区合并后仍保留两条。"""
        records = [
            build_record(
                '某医院',
                '示例市甲区测试路1号',
                license_no='1001',
                institution_type='综合医院',
            ),
            build_record(
                '某医院',
                '示例市乙区测试路2号',
                administrative_unit='甲区',
                license_no='1001',
                institution_type='综合医院',
            ),
        ]
        merged = merge_city_records(
            records, ['甲区', '乙区']
        )
        self.assertEqual(len(merged), 2)

    def test_partition_routes_cross_district_segment_to_physical_unit(self):
        """登记区在甲区的越秀段应分桶到最终地址所在区。"""
        record = build_record(
            '某医院水荫门诊部',
            '示例市乙区水荫路1号',
            final_address='示例市乙区水荫路1号',
            administrative_unit='甲区',
            license_no='1001',
            institution_type='综合医院',
        )
        partitions = partition_main_records(
            [record], ['甲区', '乙区']
        )
        self.assertEqual(len(partitions['甲区']), 0)
        self.assertEqual(len(partitions['乙区']), 1)

    def test_effective_unit_falls_back_to_original_address(self):
        """没有最终地址时按官方原文地址解析区级归属。"""
        record = build_record(
            '某医院',
            '示例市乙区水荫路1号',
            final_address='',
            administrative_unit='甲区',
        )
        self.assertEqual(
            resolve_effective_administrative_unit(
                record, ['甲区', '乙区']
            ),
            '乙区',
        )


if __name__ == '__main__':
    unittest.main()
