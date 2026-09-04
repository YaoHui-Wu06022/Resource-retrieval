"""医疗机构交付质量闸门测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from medical_quality_check import (  # noqa: E402
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


def build_record(institution_type, license_no='', index=0):
    """构造甲区带最终地址的处理记录。"""
    return {
        'place_name': f'{institution_type}示例机构{index}',
        'original_address': f'示例市甲区测试路{index + 1}号',
        'address_mode': 'government_list',
        'source_nature': 'government_information',
        'source_reference': 'https://example.gov/list | row 1',
        'attributes': {
            'administrative_unit': '甲区',
            'license_administrative_unit': '甲区',
            'subdivision_scope': 'subdivision',
            'institution_type': institution_type,
            'institution_level': '无级别',
            'license_no': license_no,
        },
        'final_address': f'示例市甲区测试路{index + 1}号',
        'map_match_status': 'skipped',
    }


def write_platform_records(root, count, clinic_count):
    """写入平台汇总记录并返回相对路径。"""
    source_dir = root / 'sources'
    source_dir.mkdir(exist_ok=True)
    records = []
    for index in range(count):
        yytype = (
            '普通诊所'
            if index < clinic_count
            else '综合医院'
        )
        records.append({
            'yymc': f'平台机构{index}',
            'yydz': '示例市甲区测试路1号',
            'szq': '甲区',
            'yytype': yytype,
            'jb': '无级别',
            '_page': 1,
            '_row': index + 1,
        })
    records_path = source_dir / 'platform_records.json'
    records_path.write_text(
        json.dumps(records, ensure_ascii=False), encoding='utf-8'
    )
    return 'sources/platform_records.json'


def write_unit_payload(root, records):
    """写出甲区 processed_address_records.json。"""
    payload = {
        'stage': 'processed_address_records',
        'city_context': build_city_context(),
        'items': records,
        'metrics': {},
    }
    (root / 'processed_address_records.json').write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8'
    )


def write_manifest(
    root,
    extra_sources=None,
    no_official_categories=None,
    include_platform=True,
):
    """写出甲区 government_source.json。"""
    sources = []
    if include_platform:
        sources.append({
            'source_id': 'platform',
            'authority': '示例市卫生健康委员会',
            'source_type': 'query_platform',
            'status': 'ready',
            'url': 'https://example.gov/platform',
            'local_file': write_platform_records(root, 20, 12),
            'snapshot_date': '2026-06-30',
            'priority': 15,
            'platform_result': {'count': 20},
        })
    if extra_sources:
        sources.extend(extra_sources)
    if no_official_categories:
        sources.append({
            'source_id': 'no_official_gap',
            'authority': '示例市卫生健康委员会',
            'source_type': '',
            'status': 'no_official_source',
            'url': '',
            'local_file': '',
            'category_coverage': no_official_categories,
        })
    manifest = {
        'stage': 'medical_institutions_government_source',
        'city_context': build_city_context(),
        'administrative_unit': {
            'name': '甲区',
            'adcode': '1',
            'level': 'district',
        },
        'sources': sources,
    }
    (root / 'government_source.json').write_text(
        json.dumps(manifest, ensure_ascii=False), encoding='utf-8'
    )


class MedicalQualityCheckTests(unittest.TestCase):
    def _run_report(
        self,
        records,
        extra_sources=None,
        no_official_categories=None,
        include_platform=True,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unit_dir = root / '甲区'
            unit_dir.mkdir()
            write_unit_payload(unit_dir, records)
            write_manifest(
                unit_dir,
                extra_sources=extra_sources,
                no_official_categories=no_official_categories,
                include_platform=include_platform,
            )
            report_path = root / 'quality_report.json'
            report = build_quality_report(
                root, report_path
            )
            return report, report_path

    def test_pass_when_counts_and_categories_meet_platform(self):
        """数量高于下界且平台大类别有交付时通过。"""
        records = [
            build_record('普通诊所', index=index) for index in range(12)
        ] + [
            build_record('综合医院', index=12 + index)
            for index in range(8)
        ]
        report, _report_path = self._run_report(records)
        self.assertTrue(report['passed'])

    def test_writes_quality_report_file(self):
        """质量报告按输出路径写出。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unit_dir = root / '甲区'
            unit_dir.mkdir()
            records = [
                build_record('普通诊所', index=index)
                for index in range(19)
            ]
            write_unit_payload(unit_dir, records)
            write_manifest(unit_dir)
            report_path = root / 'quality_report.json'
            report = build_quality_report(
                root, report_path
            )
            self.assertTrue(report['passed'])
            self.assertTrue(report_path.is_file())

    def test_fail_when_count_below_platform_lower_bound(self):
        """交付行数低于平台下界时阻断。"""
        records = [
            build_record('综合医院', index=index) for index in range(10)
        ]
        report, _report_path = self._run_report(records)
        self.assertFalse(report['passed'])
        self.assertTrue(any('低于平台下界' in reason for reason in report['reasons']))

    def test_fail_when_platform_category_missing(self):
        """平台存在的大类交付为零且无豁免时阻断。"""
        records = [
            build_record('综合医院', index=index) for index in range(19)
        ]
        report, _report_path = self._run_report(records)
        self.assertFalse(report['passed'])
        self.assertTrue(
            any('门诊部与诊所' in reason for reason in report['reasons'])
        )

    def test_pass_when_missing_category_has_official_exemption(self):
        """清单记录 no_official_source 理由后允许类别缺失。"""
        records = [
            build_record('综合医院', index=index) for index in range(19)
        ]
        report, _report_path = self._run_report(
            records,
            no_official_categories=['门诊部与诊所'],
        )
        self.assertTrue(report['passed'])

    def test_fail_without_any_ready_full_source(self):
        """没有任何 ready 全量来源时阻断。"""
        records = [
            build_record('普通诊所', index=index) for index in range(19)
        ]
        no_ready_sources = [{
            'source_id': 'gap',
            'authority': '示例市卫生健康委员会',
            'source_type': '',
            'status': 'no_official_source',
            'url': '',
            'local_file': '',
        }]
        report, _report_path = self._run_report(
            records,
            extra_sources=no_ready_sources,
            include_platform=False,
        )
        self.assertFalse(report['passed'])
        self.assertTrue(
            any('没有任何 ready' in reason for reason in report['reasons'])
        )


if __name__ == '__main__':
    unittest.main()
