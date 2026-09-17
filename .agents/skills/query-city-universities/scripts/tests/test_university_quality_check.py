"""高校交付质量闸门测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from university_quality_check import (  # noqa: E402
    build_quality_report,
)


def build_city_context():
    """构造单区城市上下文测试夹具。"""
    return {
        'stage': 'city_context',
        'input_city': '示例市',
        'city_name': '示例市',
        'province_name': '示例省',
        'subdivisions': [{'name': '甲区', 'adcode': '1', 'level': 'district'}],
    }


def build_record(address, campus_name=''):
    """构造一条带最终地址的高校处理记录。"""
    return {
        'place_name': '示例大学',
        'original_address': address,
        'address_mode': 'government_list',
        'source_nature': 'government_information',
        'source_reference': 'https://example.edu/contact | row 1',
        'attributes': {
            'school_identifier': '4144010001',
            'campus_name': campus_name,
            'source_sequence': '1',
        },
        'final_address': address,
        'map_match_status': 'skipped',
    }


def write_run_dir(root, records):
    """写入 processed_address_records.json 并返回运行目录。"""
    run_dir = root / 'Higher_Education' / '120000'
    run_dir.mkdir(parents=True)
    (run_dir / 'processed_address_records.json').write_text(
        json.dumps({
            'stage': 'processed_address_records',
            'city_context': build_city_context(),
            'items': records,
        }, ensure_ascii=False),
        encoding='utf-8',
    )
    return run_dir


class UniversityQualityCheckTests(unittest.TestCase):
    """验证高校质量闸门的通过与阻断行为。"""

    def test_clean_run_passes(self):
        """无残留问题时闸门通过并写出报告。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_run_dir(root, [build_record('示例市甲区测试路1号')])
            report = build_quality_report(run_dir, root / 'quality_report.json')
        self.assertTrue(report['passed'])
        self.assertEqual(report['checks']['main_row_count'], 1)
        self.assertEqual(report['reasons'], [])
        self.assertEqual(report['stage'], 'university_quality_report')

    def test_contact_noise_blocks(self):
        """地址残留联系词时闸门阻断。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_run_dir(
                root,
                [build_record('示例市甲区测试路1号 电话：020-12345678')],
            )
            report = build_quality_report(run_dir, root / 'quality_report.json')
        self.assertFalse(report['passed'])
        self.assertTrue(
            any('联系词' in reason for reason in report['reasons']),
            report['reasons'],
        )

    def test_abnormal_rows_are_counted(self):
        """最终地址为空的记录计入异常行且不阻断交付。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_run_dir(root, [
                build_record('示例市甲区测试路1号'),
                build_record(''),
            ])
            report = build_quality_report(run_dir, root / 'quality_report.json')
        self.assertTrue(report['passed'])
        self.assertEqual(report['checks']['main_row_count'], 1)
        self.assertEqual(report['checks']['abnormal_row_count'], 1)

    def test_missing_processed_records_raises(self):
        """缺少处理结果文件时闸门报错而不是静默通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / 'Higher_Education' / '120000'
            run_dir.mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                build_quality_report(run_dir, root / 'quality_report.json')


if __name__ == '__main__':
    unittest.main()
