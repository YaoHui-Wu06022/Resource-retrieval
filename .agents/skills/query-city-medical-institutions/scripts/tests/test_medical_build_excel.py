"""医疗机构最终工作簿生成测试。"""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import openpyxl


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'build_excel.py'
SPEC = importlib.util.spec_from_file_location(
    'medical_build_excel', SCRIPT_PATH
)
BUILD_EXCEL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILD_EXCEL
SPEC.loader.exec_module(BUILD_EXCEL)


def build_city_context():
    """构造城市上下文测试夹具。"""
    return {
        'stage': 'city_context',
        'input_city': '示例市',
        'city_name': '示例市',
        'province_name': '示例省',
        'subdivisions': [
            {'name': '甲区', 'adcode': '1', 'level': 'district'},
        ],
    }


def build_record(
    place_name,
    original_address,
    final_address,
    map_match_status='skipped',
):
    """构造一条已处理地址记录。"""
    return {
        'place_name': place_name,
        'original_address': original_address,
        'address_mode': 'government_list',
        'source_nature': 'government_information',
        'source_reference': 'https://example.gov/list | list.html | row 1',
        'attributes': {
            'administrative_unit': '甲区',
            'license_administrative_unit': '甲区',
            'subdivision_scope': 'subdivision',
            'institution_type': '综合医院',
            'institution_level': '三级',
        },
        'normalized_address': original_address,
        'map_match_status': map_match_status,
        'map_reason': '',
        'final_address': final_address,
        'final_address_source': 'official' if final_address else '',
        'final_address_reason': '政府资料地址' if final_address else '',
    }


class MedicalBuildExcelTests(unittest.TestCase):
    def test_ungraded_level_values_are_blank_in_domain_output(self):
        """未定级/无定级/无级别在工作簿输出中显示为空。"""
        for level_value in ('未定级', '无定级', '无级别'):
            values = BUILD_EXCEL._domain_values({
                'attributes': {
                    'administrative_unit': '甲区',
                    'institution_type': '综合医院',
                    'institution_level': level_value,
                },
            })
            self.assertEqual(values[3], '')
        graded_values = BUILD_EXCEL._domain_values({
            'attributes': {
                'administrative_unit': '甲区',
                'institution_type': '综合医院',
                'institution_level': '三级',
            },
        })
        self.assertEqual(graded_values[3], '三级')

    def test_effective_admin_prefers_final_address_district(self):
        """最终地址含区名时优先使用该区，执照区只作兜底。"""
        record = build_record(
            '示例医院',
            '花地大道南30-32号',
            '示例市乙区花地大道南30-32号',
        )
        record['attributes']['administrative_unit'] = ''
        record['attributes']['license_administrative_unit'] = '甲区'
        self.assertEqual(
            BUILD_EXCEL.resolve_effective_administrative_unit(
                record, ['甲区', '乙区']
            ),
            '乙区',
        )
        record['final_address'] = '示例市花地大道南30-32号'
        self.assertEqual(
            BUILD_EXCEL.resolve_effective_administrative_unit(
                record, ['甲区', '乙区']
            ),
            '甲区',
        )

    def test_main_builds_unit_and_city_workbooks_without_anomaly_file(self):
        """从各行政单位目录生成区级工作簿与城市总表。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unit_dir = root / '甲区'
            unit_dir.mkdir()
            items = [
                build_record(
                    '甲区人民医院',
                    '示例市甲区测试路1号',
                    '示例市甲区测试路1号',
                ),
                build_record(
                    '甲区口腔门诊',
                    '示例市甲区测试路2号',
                    '',
                ),
                build_record(
                    '无地址诊所',
                    '',
                    '',
                ),
            ]
            processed_path = unit_dir / 'processed_address_records.json'
            processed_path.write_text(json.dumps({
                'stage': 'processed_address_records',
                'city_context': build_city_context(),
                'items': items,
                'metrics': {},
            }, ensure_ascii=False), encoding='utf-8')
            output_path = root / '医疗机构信息_示例市_2026-09-03.xlsx'
            old_argv = sys.argv
            sys.argv = [
                'build_excel',
                '--input-dir', str(root),
                '--output', str(output_path),
            ]
            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    BUILD_EXCEL.main()
            finally:
                sys.argv = old_argv
            self.assertTrue(output_path.is_file())
            city_workbook = openpyxl.load_workbook(output_path)
            self.assertEqual(city_workbook.sheetnames, ['机构信息', '甲区'])
            self.assertNotIn('异常机构', city_workbook.sheetnames)
            main_sheet = city_workbook['机构信息']
            self.assertEqual(main_sheet.max_row, 3)
            unit_sheet = city_workbook['甲区']
            self.assertEqual(unit_sheet.max_row, 3)
            district_path = unit_dir / '医疗机构信息_甲区.xlsx'
            self.assertTrue(district_path.is_file())
            district_workbook = openpyxl.load_workbook(district_path)
            self.assertEqual(
                district_workbook.sheetnames, ['机构信息', '异常机构']
            )
            district_abnormal_sheet = district_workbook['异常机构']
            self.assertEqual(district_abnormal_sheet.max_row, 2)


if __name__ == '__main__':
    unittest.main()
