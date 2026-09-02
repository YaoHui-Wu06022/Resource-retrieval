"""并发官网运行器测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_university_fetch import (
    build_fetch_report,
    build_slices,
    parse_process_summaries,
    run_university_fetch,
    validate_manifest,
    write_static_results,
)
from query_city_core.io_utils import write_json_payload


def build_city_payload(identifiers):
    """构造与域名清单对应的城市高校名录。"""
    return {
        'stage': 'city_universities',
        'city_context': {
            'stage': 'city_context',
            'input_city': '广州市',
            'city_name': '广州市',
            'province_name': '广东省',
            'subdivisions': [],
        },
        'schools': [
            {
                'source_sequence': str(index + 1),
                'school_name': f'示例大学{index + 1}',
                'school_identifier': identifier,
                'supervising_authority': '广东省教育厅',
                'location_city': '广州市',
                'education_level': '本科',
                'school_tag': '',
                'school_nature': '公办',
            }
            for index, identifier in enumerate(identifiers)
        ],
    }


def build_manifest(items):
    """构造域名清单。"""
    return {'stage': 'official_domain_manifest', 'items': items}


class ValidateManifestTests(unittest.TestCase):
    def test_splits_fetch_no_site_and_skipped_items(self):
        """域名清单按状态拆分成三类处理项。"""
        city = build_city_payload(['1001', '1002', '1003'])
        manifest = build_manifest([
            {
                'school_identifier': '1001',
                'home_url': 'https://www.a.edu.cn/',
                'official_domains': ['a.edu.cn'],
            },
            {
                'school_identifier': '1002',
                'no_official_site': True,
                'evidence_url': 'https://www.gov.cn/record',
                'reason': '2026 年新设，无独立官网',
            },
            {
                'school_identifier': '1003',
                'processing_status': 'skipped',
                'skip_reason': 'merged',
                'skip_reference': 'https://www.gov.cn/notice',
            },
        ])

        fetch_items, no_site_items, skipped_items, city_index = validate_manifest(
            manifest, city
        )

        self.assertEqual(
            [item['school_identifier'] for item in fetch_items],
            ['1001'],
        )
        self.assertEqual(
            [item['school_identifier'] for item in no_site_items],
            ['1002'],
        )
        self.assertEqual(
            [item['school_identifier'] for item in skipped_items],
            ['1003'],
        )
        self.assertEqual(len(city_index), 3)

    def test_rejects_missing_or_duplicate_schools(self):
        """域名清单必须与城市名录一一对应。"""
        city = build_city_payload(['1001', '1002'])
        manifest = build_manifest([
            {
                'school_identifier': '1001',
                'home_url': 'https://www.a.edu.cn/',
                'official_domains': ['a.edu.cn'],
            },
        ])
        with self.assertRaisesRegex(ValueError, '域名清单缺少学校'):
            validate_manifest(manifest, city)

        duplicate = build_manifest([
            {
                'school_identifier': '1001',
                'home_url': 'https://www.a.edu.cn/',
                'official_domains': ['a.edu.cn'],
            },
            {
                'school_identifier': '1001',
                'home_url': 'https://www.a.edu.cn/contact',
                'official_domains': ['a.edu.cn'],
            },
            {
                'school_identifier': '1002',
                'home_url': 'https://www.b.edu.cn/',
                'official_domains': ['b.edu.cn'],
            },
        ])
        with self.assertRaisesRegex(ValueError, '学校标识码重复'):
            validate_manifest(duplicate, city)


class SliceAndStaticResultTests(unittest.TestCase):
    def test_build_slices_cover_all_items_exactly_once(self):
        """切片互不重叠且覆盖全部学校。"""
        items = [
            {'school_identifier': f'{index:04d}'}
            for index in range(10)
        ]
        slices = build_slices(items, 3)
        flat = [
            item['school_identifier']
            for slice_items in slices
            for item in slice_items
        ]
        self.assertEqual(len(slices), 3)
        self.assertEqual(flat, [item['school_identifier'] for item in items])
        self.assertEqual(len(set(flat)), len(items))

    def test_build_slices_returns_empty_for_no_items(self):
        self.assertEqual(build_slices([], 3), [])

    def test_write_static_results_writes_no_site_and_skipped(self):
        """无官网与合并停办结果由运行器直接写出。"""
        with tempfile.TemporaryDirectory() as directory:
            write_static_results(
                [{
                    'school_identifier': '1001',
                    'evidence_url': 'https://www.gov.cn/record',
                    'reason': '无官网',
                }],
                [{
                    'school_identifier': '1002',
                    'skip_reason': 'merged',
                    'skip_reference': 'https://www.gov.cn/notice',
                }],
                directory,
            )
            no_site = json.loads(
                (Path(directory) / 'school_results' / '1001.json')
                .read_text(encoding='utf-8')
            )
            skipped = json.loads(
                (Path(directory) / 'school_results' / '1002.json')
                .read_text(encoding='utf-8')
            )

        self.assertEqual(no_site['processing_status'], 'no_official_site')
        self.assertEqual(no_site['evidence_url'], 'https://www.gov.cn/record')
        self.assertEqual(skipped['processing_status'], 'skipped')
        self.assertEqual(skipped['skip_reason'], 'merged')


class FetchReportTests(unittest.TestCase):
    def test_parse_process_summaries(self):
        """正常退出的抓取进程 stdout 摘要被解析。"""
        summaries = parse_process_summaries(
            0,
            json.dumps({'items': [{
                'school_identifier': '1001',
                'processing_status': 'completed',
                'page_count': 2,
                'has_address_candidate': True,
            }]}),
        )
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]['school_identifier'], '1001')
        self.assertEqual(parse_process_summaries(1, 'boom'), [])

    def test_build_fetch_report_reads_result_files(self):
        """fetch_report 按城市名录汇总每校状态与地址候选。"""
        city = build_city_payload(['1001', '1002', '1003'])
        city_index = {
            school['school_identifier']: school
            for school in city['schools']
        }
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / 'school_results').mkdir()
            write_json_payload(
                run_dir / 'school_results' / '1001.json',
                {
                    'school_identifier': '1001',
                    'processing_status': 'completed',
                    'pages': [{
                        'stage': 'address_candidates',
                        'requested_url': 'https://www.a.edu.cn/',
                        'address_candidates': [{
                            'address_text': '广州市天河区示例路1号',
                        }],
                        'campus_hints': [],
                    }],
                },
            )
            write_json_payload(
                run_dir / 'school_results' / '1002.json',
                {
                    'school_identifier': '1002',
                    'processing_status': 'no_official_site',
                    'evidence_url': 'https://www.gov.cn/record',
                    'reason': '无官网',
                },
            )
            report_items = build_fetch_report(run_dir, city_index)

        by_identifier = {item['school_identifier']: item for item in report_items}
        self.assertTrue(by_identifier['1001']['has_address_candidate'])
        self.assertEqual(by_identifier['1001']['page_count'], 1)
        self.assertEqual(
            by_identifier['1002']['processing_status'],
            'no_official_site',
        )
        self.assertEqual(by_identifier['1003']['processing_status'], 'missing')

    def test_run_university_fetch_with_static_manifest_only(self):
        """全静态清单（无浏览器项）可完整跑通并产出报告。"""
        city = build_city_payload(['1001', '1002'])
        manifest = build_manifest([
            {
                'school_identifier': '1001',
                'no_official_site': True,
                'evidence_url': 'https://www.gov.cn/record',
                'reason': '无官网',
            },
            {
                'school_identifier': '1002',
                'processing_status': 'skipped',
                'skip_reason': 'merged',
                'skip_reference': 'https://www.gov.cn/notice',
            },
        ])
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            write_json_payload(run_dir / 'city_universities.json', city)
            manifest_path = run_dir / 'official_domain_manifest.json'
            write_json_payload(manifest_path, manifest)
            result = run_university_fetch(
                str(manifest_path),
                str(run_dir),
                workers=2,
                max_pages=3,
            )
            report = json.loads(
                (run_dir / 'fetch_report.json').read_text(encoding='utf-8')
            )

        self.assertEqual(result['no_official_site_count'], 1)
        self.assertEqual(result['missing_count'], 0)
        statuses = {
            item['school_identifier']: item['processing_status']
            for item in report['items']
        }
        self.assertEqual(statuses['1001'], 'no_official_site')
        self.assertEqual(statuses['1002'], 'skipped')


if __name__ == '__main__':
    unittest.main()
