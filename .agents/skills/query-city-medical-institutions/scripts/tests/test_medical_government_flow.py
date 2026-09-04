"""医疗机构通用政府来源流程测试。"""

import json
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from medical_government_flow import (  # noqa: E402
    build_address_records,
    build_medical_extraction_plan,
    build_platform_query_url,
    collect_platform_pages,
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
    def test_query_platform_records_go_through_generic_engine(self):
        """平台汇总 JSON 记录经对象列表规则提取为地址记录。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records_path = root / 'records.json'
            records_path.write_text(json.dumps([{
                'yymc': '平台综合医院',
                'yydz': '示例市甲区测试路1号',
                'szq': '甲区',
                'yytype': '综合医院',
                'jb': '三级',
                '_page': 1,
                '_row': 1,
            }], ensure_ascii=False), encoding='utf-8')
            manifest = {
                'stage': 'medical_institutions_government_source',
                'city_context': build_city_context(),
                'administrative_unit': build_administrative_unit(),
                'sources': [{
                    'source_id': 'example_platform',
                    'authority': '示例市卫生健康委员会',
                    'source_type': 'query_platform',
                    'url': 'https://example.gov/platform',
                    'local_file': 'records.json',
                    'snapshot_date': '2026-06-30',
                    'priority': 15,
                    'status': 'ready',
                }],
            }
            manifest_path = root / 'government_source.json'
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding='utf-8',
            )
            plan_path = root / 'extraction_plan.json'
            plan, exit_code = build_medical_extraction_plan(
                manifest_path, plan_path
            )
            self.assertEqual(exit_code, 0)
            object_rules = [
                rule
                for rule in plan['items'][0]['extraction_rules']
                if rule.get('kind') == 'object_list'
            ]
            self.assertEqual(object_rules[0]['object_format'], 'json')
            self.assertEqual(
                object_rules[0]['place_name_keys'], ['yymc']
            )
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
        self.assertEqual(record['place_name'], '平台综合医院')
        self.assertEqual(
            record['attributes']['administrative_unit'], '甲区'
        )

    def test_build_platform_query_url_applies_district_filter(self):
        """平台查询 URL 包含区过滤 JSON 与分页参数。"""
        source_item = {
            'platform': {
                'endpoint': 'https://search.example.gov/jsonp/site/1',
                'allowed_domain': 'search.example.gov',
                'callback': 'cb',
                'fixed_params': {'category_id': '66705'},
                'paging': {
                    'page_param': 'page',
                    'page_size_param': 'pagesize',
                    'page_size': 500,
                },
                'district_filter': {'key': 'szq'},
            },
        }
        page_url = build_platform_query_url(
            source_item, '甲区', 3
        )
        parsed = urlparse(page_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query['page'], ['3'])
        self.assertEqual(query['pagesize'], ['500'])
        self.assertEqual(query['category_id'], ['66705'])
        self.assertIn('甲区', query['json_ext_in'][0])

    def test_collect_platform_pages_pages_until_count(self):
        """分页采集按 count 收齐并保存每页原文审计。"""
        source_item = {
            'platform': {
                'endpoint': 'https://search.example.gov/jsonp/site/1',
                'allowed_domain': 'search.example.gov',
                'callback': 'cb',
                'fixed_params': {},
                'paging': {
                    'page_param': 'page',
                    'page_size_param': 'pagesize',
                    'page_size': 2,
                    'total_field': 'count',
                    'list_field': 'results',
                },
                'district_filter': {'key': 'szq'},
                'json_ext_field': 'json_ext',
            },
        }

        def fake_fetch(page_url, _allowed_domain, _timeout):
            query = parse_qs(urlparse(page_url).query)
            page_number = int(query['page'][0])
            if page_number == 1:
                payload = {'count': 3, 'results': [
                    {'id': '1', 'json_ext': json.dumps({
                        'yymc': '医院一', 'yydz': '示例市甲区路1号',
                        'szq': '甲区', 'yytype': '综合医院',
                    }, ensure_ascii=False)},
                    {'id': '2', 'json_ext': json.dumps({
                        'yymc': '诊所一', 'yydz': '示例市甲区路2号',
                        'szq': '甲区', 'yytype': '普通诊所',
                    }, ensure_ascii=False)},
                ]}
            else:
                payload = {'count': 3, 'results': [
                    {'id': '3', 'json_ext': json.dumps({
                        'yymc': '检验实验室一',
                        'yydz': '示例市甲区路3号',
                        'szq': '甲区', 'yytype': '医学检验实验室',
                    }, ensure_ascii=False)},
                ]}
            return 'cb(' + json.dumps(
                payload, ensure_ascii=False
            ) + ')', {'url': page_url}

        records, page_audits, total_count, raw_texts = (
            collect_platform_pages(
                source_item, '甲区', fetch_page=fake_fetch
            )
        )
        self.assertEqual(total_count, 3)
        self.assertEqual(len(records), 3)
        self.assertEqual(len(page_audits), 2)
        self.assertEqual(len(raw_texts), 2)
        self.assertEqual(records[2]['_page'], 2)

    def test_collect_platform_pages_rejects_count_mismatch(self):
        """分页总数收不齐时抛出错误。"""
        source_item = {
            'platform': {
                'endpoint': 'https://search.example.gov/jsonp/site/1',
                'allowed_domain': 'search.example.gov',
                'callback': 'cb',
                'fixed_params': {},
                'paging': {
                    'page_param': 'page',
                    'page_size_param': 'pagesize',
                    'page_size': 2,
                    'total_field': 'count',
                    'list_field': 'results',
                },
                'district_filter': {'key': 'szq'},
                'json_ext_field': 'json_ext',
            },
        }

        def fake_fetch(page_url, _allowed_domain, _timeout):
            query = parse_qs(urlparse(page_url).query)
            page_number = int(query['page'][0])
            payload = {'count': 5, 'results': [
                {'id': str(page_number * 10 + index), 'json_ext': '{}'}
                for index in range(2)
            ]}
            return 'cb(' + json.dumps(
                payload, ensure_ascii=False
            ) + ')', {'url': page_url}

        with self.assertRaises(ValueError):
            collect_platform_pages(
                source_item, '甲区', fetch_page=fake_fetch
            )

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
