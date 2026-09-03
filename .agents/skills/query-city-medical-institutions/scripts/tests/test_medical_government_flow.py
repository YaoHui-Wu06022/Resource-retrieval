"""医疗机构通用政府来源流程测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from medical_government_flow import (  # noqa: E402
    build_address_records,
    build_medical_extraction_plan,
    extract_medical_records,
)


def build_city_context():
    """构造城市上下文测试夹具。"""
    return {
        'stage': 'city_context',
        'input_city': '示例市',
        'city_name': '示例市',
        'province_name': '示例省',
        'subdivisions': [{'name': '甲区', 'adcode': '1', 'level': 'district'}],
    }


def build_administrative_unit():
    """构造来源清单使用的行政单位测试夹具。"""
    return {'name': '甲区', 'adcode': '1', 'level': 'district'}


class MedicalGovernmentFlowTests(unittest.TestCase):
    def test_embedded_html_list_goes_through_generic_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / 'list.html'
            html_path.write_text(
                '<script>var searchfg={fg:[{'
                '"jgmc":"示例医院",'
                '"dz":"示例市甲区测试路1号",'
                '"jb":"三级",'
                '"xzqh":"甲区",'
                '"docurl":"https://example.gov/detail"}]};</script>',
                encoding='utf-8',
            )
            manifest = {
                'stage': 'medical_institutions_government_source',
                'city_context': build_city_context(),
                'administrative_unit': build_administrative_unit(),
                'sources': [{
                    'source_id': 'example_list',
                    'authority': '示例市卫生健康委员会',
                    'source_type': 'embedded_html_list',
                    'record_kind': 'license_list',
                    'url': 'https://example.gov/list',
                    'local_file': 'list.html',
                    'snapshot_date': '2026-09-03',
                    'priority': 10,
                    'status': 'ready',
                }],
            }
            manifest_path = root / 'government_source.json'
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding='utf-8'
            )
            plan_path = root / 'extraction_plan.json'
            plan, exit_code = build_medical_extraction_plan(
                manifest_path, plan_path
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                plan['administrative_unit']['name'], '甲区'
            )
            object_rules = [
                rule for rule in plan['items'][0]['extraction_rules']
                if rule.get('kind') == 'object_list'
            ]
            self.assertTrue(object_rules, plan)
            plan['items'][0]['review_status'] = 'ready'
            for rule in plan['items'][0]['extraction_rules']:
                if rule.get('kind') == 'object_list':
                    rule['approved'] = True
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False), encoding='utf-8'
            )
            payload = extract_medical_records(
                plan_path, root / 'address_records.json'
            )
        self.assertEqual(payload['errors'], [])
        self.assertEqual(payload['metrics']['record_count'], 1)
        record = payload['items'][0]
        self.assertEqual(record['place_name'], '示例医院')
        self.assertEqual(
            record['attributes']['institution_level'], '三级'
        )
        self.assertEqual(
            record['attributes']['administrative_unit'], '甲区'
        )
        self.assertEqual(
            record['attributes']['subdivision_scope'], 'subdivision'
        )


def build_raw_item(address, source_reference='https://example.gov/list | list.html | row 3'):
    """构造一条供记录拆分测试使用的中性原始记录。"""
    return {
        'place_name': '示例医院',
        'original_address': address,
        'source_reference': source_reference,
        'row': 3,
        'attributes': {
            'administrative_unit': '甲区',
            'institution_type': '综合医院',
            'institution_level': '三级',
            'license_no': '1001',
        },
        'source_item': {
            'source_id': 'example_list',
            'authority': '示例市卫生健康委员会',
            'snapshot_date': '2026-09-03',
            'priority': 10,
            'foreign_phrases': ['佛山市'],
        },
    }


class MedicalFlowRecordTests(unittest.TestCase):
    def test_multi_segment_references_do_not_accumulate(self):
        city_context = build_city_context()
        raw_item = build_raw_item('示例市甲区测试路1号、乙街2号')
        records = build_address_records(
            raw_item, city_context, {}, '甲区'
        )
        self.assertEqual([record['source_reference'] for record in records], [
            'https://example.gov/list | list.html | row 3 | 地址 1',
            'https://example.gov/list | list.html | row 3 | 地址 2',
        ])
        self.assertEqual(
            records[0]['attributes']['administrative_unit'], '甲区'
        )
        self.assertEqual(
            records[1]['attributes']['administrative_unit'], '甲区'
        )
        self.assertEqual(
            records[1]['attributes']['license_administrative_unit'], '甲区'
        )

    def test_single_segment_without_district_uses_target_unit(self):
        """按区检索时，无区名地址以目标行政区作 norm 目标区。"""
        city_context = build_city_context()
        raw_item = build_raw_item('示例市测试路1号')
        records = build_address_records(
            raw_item, city_context, {}, '甲区'
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]['attributes']['administrative_unit'], '甲区'
        )
        self.assertEqual(
            records[0]['attributes']['subdivision_scope'], 'subdivision'
        )
        self.assertEqual(
            records[0]['attributes']['license_administrative_unit'], '甲区'
        )

    def test_foreign_segment_is_removed_and_counted(self):
        city_context = build_city_context()
        counters = {}
        raw_item = build_raw_item('佛山市禅城区外地路1号、示例市甲区测试路1号')
        records = build_address_records(
            raw_item, city_context, counters, '甲区'
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['original_address'], '示例市甲区测试路1号')
        self.assertEqual(counters['removed_foreign_count'], 1)

    def test_empty_address_record_is_kept(self):
        city_context = build_city_context()
        raw_item = build_raw_item('')
        records = build_address_records(
            raw_item, city_context, {}, '甲区'
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['original_address'], '')
        self.assertEqual(
            records[0]['attributes']['administrative_unit'], '甲区'
        )

    def test_out_of_scope_source_row_is_skipped_and_counted(self):
        """跨区来源只保留属于当前行政单位的行。"""
        city_context = build_city_context()
        counters = {}
        raw_item = build_raw_item('示例市乙区测试路1号')
        raw_item['attributes']['administrative_unit'] = '乙区'
        records = build_address_records(
            raw_item, city_context, counters, '甲区'
        )
        self.assertEqual(records, [])
        self.assertEqual(counters['skipped_out_of_scope_count'], 1)


if __name__ == '__main__':
    unittest.main()
