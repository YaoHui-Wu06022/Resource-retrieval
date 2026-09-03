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
    build_medical_extraction_plan,
    extract_medical_records,
)


def build_city_context():
    return {
        'stage': 'city_context',
        'input_city': '示例市',
        'city_name': '示例市',
        'province_name': '示例省',
        'subdivisions': [{'name': '甲区', 'adcode': '1', 'level': 'district'}],
    }


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


if __name__ == '__main__':
    unittest.main()
