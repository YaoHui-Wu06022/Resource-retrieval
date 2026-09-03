"""高校域名阶段命令测试（probe 探测与 merge 汇总）。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from university_domain import merge_domain_batches, probe_domain_batches
from query_city_core.io_utils import write_json_payload


def build_probe_city_payload(schools):
    """构造探测场景的城市高校名录。"""
    return {
        'stage': 'city_universities',
        'city_context': {
            'stage': 'city_context',
            'city_name': '广州市',
            'subdivisions': [],
        },
        'schools': [
            {
                'source_sequence': str(index + 1),
                'school_name': name,
                'school_identifier': identifier,
                'location_city': '广州市',
                'education_level': '本科',
            }
            for index, (identifier, name) in enumerate(schools)
        ],
    }


def build_merge_city_payload(identifiers):
    """构造汇总场景的城市高校名录。"""
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


def build_run_dir(city_identifiers, batch_items):
    """构造含 city_universities 与单个批次的临时运行目录。"""
    temporary_dir = tempfile.TemporaryDirectory()
    run_dir = Path(temporary_dir.name)
    write_json_payload(
        run_dir / 'city_universities.json',
        build_merge_city_payload(city_identifiers),
    )
    batch_dir = run_dir / 'domain_batches'
    batch_dir.mkdir()
    write_json_payload(
        batch_dir / 'domain_batch_1.json',
        {'stage': 'domain_batch', 'items': batch_items},
    )
    return temporary_dir, run_dir


class DomainProbeAdapterTests(unittest.TestCase):
    def test_probe_domain_batches_writes_generic_report(self):
        """高校批次适配为 place_id/place_name 后写入探测报告。"""
        city = build_probe_city_payload([
            ('1001', '甲大学'),
            ('1002', '乙大学'),
        ])
        batch = {
            'stage': 'domain_batch',
            'items': [
                {
                    'school_identifier': '1001',
                    'school_name': '甲大学',
                    'home_url': 'https://www.a.edu.cn/',
                    'official_domains': ['a.edu.cn'],
                },
                {
                    'school_identifier': '1002',
                    'no_official_site': True,
                    'evidence_url': 'https://gaokao.chsi.com.cn/record',
                    'reason': '无独立官网',
                },
            ],
        }

        def fake_fetch(url):
            return (
                '<title>甲大学</title>'.encode('utf-8'),
                url,
                200,
                [],
                'utf-8',
            )

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            write_json_payload(run_dir / 'city_universities.json', city)
            batch_dir = run_dir / 'domain_batches'
            batch_dir.mkdir()
            write_json_payload(batch_dir / 'domain_batch_01.json', batch)
            result = probe_domain_batches(str(run_dir), fetch=fake_fetch)
            report = json.loads(
                (run_dir / 'domain_probe_report.json').read_text(encoding='utf-8')
            )

        self.assertEqual(result['probed_count'], 1)
        self.assertEqual(result['issue_count'], 0)
        self.assertEqual(report['items'][0]['place_id'], '1001')
        self.assertEqual(report['items'][0]['place_name'], '甲大学')


class MergeDomainBatchesTests(unittest.TestCase):
    def test_merges_mixed_conclusions_in_city_order(self):
        """普通、无官网与跳过项按城市名录顺序汇总。"""
        temporary_dir, run_dir = build_run_dir(
            ['1001', '1002', '1003'],
            [
                {
                    'school_identifier': '1002',
                    'no_official_site': True,
                    'evidence_url': 'https://www.gov.cn/record',
                    'reason': '新设校无官网',
                },
                {
                    'school_identifier': '1001',
                    'home_url': 'https://www.a.edu.cn/',
                    'official_domains': ['a.edu.cn'],
                    'candidate_urls': ['https://www.a.edu.cn/contact'],
                },
                {
                    'school_identifier': '1003',
                    'processing_status': 'skipped',
                    'skip_reason': 'merged',
                    'skip_reference': 'https://www.gov.cn/notice',
                },
            ],
        )
        try:
            result = merge_domain_batches(str(run_dir))
            manifest = json.loads(
                (run_dir / 'official_domain_manifest.json')
                .read_text(encoding='utf-8')
            )
        finally:
            temporary_dir.cleanup()

        self.assertEqual(result['school_count'], 3)
        self.assertEqual(
            [item['school_identifier'] for item in manifest['items']],
            ['1001', '1002', '1003'],
        )
        self.assertEqual(
            manifest['items'][0]['candidate_urls'],
            ['https://www.a.edu.cn/contact'],
        )
        self.assertTrue(manifest['items'][1]['no_official_site'])

    def test_rejects_missing_or_duplicate_schools(self):
        """批次必须与城市名录一一对应。"""
        temporary_dir, run_dir = build_run_dir(
            ['1001', '1002'],
            [{
                'school_identifier': '1001',
                'home_url': 'https://www.a.edu.cn/',
                'official_domains': ['a.edu.cn'],
            }],
        )
        try:
            with self.assertRaisesRegex(ValueError, '域名批次缺少学校'):
                merge_domain_batches(str(run_dir))
        finally:
            temporary_dir.cleanup()

        temporary_dir, run_dir = build_run_dir(
            ['1001'],
            [
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
            ],
        )
        try:
            with self.assertRaisesRegex(ValueError, '学校标识码重复'):
                merge_domain_batches(str(run_dir))
        finally:
            temporary_dir.cleanup()

    def test_refuses_output_when_failure_reason_exists(self):
        """存在 failure_reason 时拒绝输出域名清单。"""
        temporary_dir, run_dir = build_run_dir(
            ['1001'],
            [{
                'school_identifier': '1001',
                'failure_reason': 'WebSearch 未确认归属官网',
            }],
        )
        try:
            with self.assertRaisesRegex(ValueError, '拒绝输出域名清单'):
                merge_domain_batches(str(run_dir))
            self.assertFalse(
                (run_dir / 'official_domain_manifest.json').exists()
            )
        finally:
            temporary_dir.cleanup()

    def test_rejects_invalid_skip_reason(self):
        """跳过项必须使用合法 skip_reason。"""
        temporary_dir, run_dir = build_run_dir(
            ['1001'],
            [{
                'school_identifier': '1001',
                'processing_status': 'skipped',
                'skip_reason': 'no_site',
                'skip_reference': 'https://www.gov.cn/notice',
            }],
        )
        try:
            with self.assertRaisesRegex(ValueError, '跳过项必须包含合法'):
                merge_domain_batches(str(run_dir))
        finally:
            temporary_dir.cleanup()


if __name__ == '__main__':
    unittest.main()
