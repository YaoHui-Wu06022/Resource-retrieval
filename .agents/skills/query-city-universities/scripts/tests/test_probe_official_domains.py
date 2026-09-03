"""高校域名现用性探测适配层测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from probe_official_domains import probe_domain_batches
from query_city_core.io_utils import write_json_payload


def build_city_payload(schools):
    """构造城市高校名录。"""
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


class DomainProbeAdapterTests(unittest.TestCase):
    def test_probe_domain_batches_writes_generic_report(self):
        """高校批次适配为 place_id/place_name 后写入探测报告。"""
        city = build_city_payload([
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


if __name__ == '__main__':
    unittest.main()
