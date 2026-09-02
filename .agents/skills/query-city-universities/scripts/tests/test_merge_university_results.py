"""逐校高校检索结果合并测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from merge_university_results import merge_school_results


def build_city_universities_payload():
    """构造包含两所学校的基础信息。"""
    schools = []
    for sequence, identifier, name in (
        ('1', '1001', '甲大学'),
        ('2', '1002', '乙大学'),
    ):
        schools.append({
            'source_sequence': sequence,
            'school_name': name,
            'school_identifier': identifier,
            'supervising_authority': '测试部门',
            'location_city': '广州市',
            'education_level': '本科',
            'school_tag': '',
            'school_nature': '公办',
        })
    return {
        'stage': 'city_universities',
        'city_context': {
            'stage': 'city_context',
            'input_city': '广州市',
            'city_name': '广州市',
            'province_name': '广东省',
            'subdivisions': [],
        },
        'schools': schools,
    }


def build_page(url='https://example.edu.cn/'):
    """构造最小合法单页结果。"""
    return {
        'stage': 'address_candidates',
        'requested_url': url,
        'address_candidates': [],
        'campus_hints': [],
    }


def write_school_result(directory, filename, payload):
    """写入测试用逐校结果文件。"""
    path = Path(directory) / filename
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding='utf-8',
    )


class MergeUniversityResultsTest(unittest.TestCase):
    def test_merge_accepts_no_official_site_result(self):
        """无官网学校结果可通过合并校验。"""
        with tempfile.TemporaryDirectory() as directory:
            write_school_result(directory, '1001.json', {
                'school_identifier': '1001',
                'processing_status': 'no_official_site',
                'evidence_url': 'https://example.gov.cn/record',
                'reason': '2026 年新设，无独立官网',
            })
            write_school_result(directory, '1002.json', {
                'school_identifier': '1002',
                'processing_status': 'completed',
                'pages': [build_page()],
            })

            payload = merge_school_results(
                directory,
                build_city_universities_payload(),
            )

        self.assertEqual(
            [item['school_identifier'] for item in payload['items']],
            ['1001', '1002'],
        )
        self.assertEqual(
            payload['items'][0]['processing_status'],
            'no_official_site',
        )

    def test_merge_orders_results_by_city_universities(self):
        with tempfile.TemporaryDirectory() as directory:
            write_school_result(directory, '1002.json', {
                'school_identifier': '1002',
                'processing_status': 'completed',
                'pages': [build_page('https://b.example.edu.cn/')],
            })
            write_school_result(directory, '1001.json', {
                'school_identifier': '1001',
                'processing_status': 'completed',
                'pages': [build_page('https://a.example.edu.cn/')],
            })

            payload = merge_school_results(directory, build_city_universities_payload())

        self.assertEqual(
            [item['school_identifier'] for item in payload['items']],
            ['1001', '1002'],
        )

    def test_merge_rejects_missing_school_result(self):
        with tempfile.TemporaryDirectory() as directory:
            write_school_result(directory, '1001.json', {
                'school_identifier': '1001',
                'processing_status': 'completed',
                'pages': [build_page()],
            })
            with self.assertRaisesRegex(ValueError, '缺少学校处理结果'):
                merge_school_results(directory, build_city_universities_payload())

    def test_merge_rejects_filename_identifier_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            write_school_result(directory, 'wrong.json', {
                'school_identifier': '1001',
                'processing_status': 'completed',
                'pages': [build_page()],
            })
            with self.assertRaisesRegex(ValueError, '文件名必须等于学校标识码'):
                merge_school_results(directory, build_city_universities_payload())

    def test_merge_rejects_page_budget_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            write_school_result(directory, '1001.json', {
                'school_identifier': '1001',
                'processing_status': 'completed',
                'pages': [build_page()] * 7,
            })
            write_school_result(directory, '1002.json', {
                'school_identifier': '1002',
                'processing_status': 'completed',
                'pages': [build_page()],
            })
            with self.assertRaisesRegex(ValueError, '页面数量超过6页预算'):
                merge_school_results(directory, build_city_universities_payload())


if __name__ == '__main__':
    unittest.main()
