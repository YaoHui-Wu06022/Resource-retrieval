"""官方来源通用检查/提取引擎测试。"""

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl

from query_city_core.official.extract import (
    AttributeTerm,
    FieldTerms,
    extract_government_records,
    inspect_government_source,
)
from query_city_core.official.readers import normalize_text


def build_terms():
    """构造非学校场景词表，验证引擎不绑定业务语义。"""
    return FieldTerms(
        place_headers=('机构名称', '单位名称'),
        exact_place_headers=('名称',),
        address_headers=('地址', '详细地址'),
        attribute_terms=(
            AttributeTerm('category', headers=('机构类别',), label_text='机构类别'),
            AttributeTerm('nature', headers=('机构性质',), label_text='机构性质'),
        ),
        place_marker_pattern=r'(?:医院|中心|站)',
        address_marker_pattern=r'(?:路|街|号|园区)',
        excluded_place_label_pattern=r'机构类别|上级单位',
    )


def build_city_context():
    """构造合法的城市上下文。"""
    return {
        'stage': 'city_context',
        'input_city': '示例市',
        'city_name': '示例市',
        'province_name': '示例省',
        'subdivisions': [
            {'name': '甲区', 'adcode': '000001', 'level': 'district'},
        ],
    }


def build_manifest(items):
    """构造可被 inspect 使用的来源清单。"""
    return {
        'stage': 'scene_government_source',
        'city_context': build_city_context(),
        'items': items,
    }


def approve_rule(plan_payload):
    """把计划中所有规则标记为已批准并把来源标记为 ready。"""
    for source_plan in plan_payload['items']:
        source_plan['review_status'] = 'ready'
        for rule in source_plan.get('extraction_rules') or []:
            rule['approved'] = True
    return plan_payload


def build_address_record(raw_item):
    """场景回调：把中性原始记录转成最小地址记录。"""
    return [{
        'place_name': raw_item['place_name'],
        'original_address': raw_item['original_address'],
        'source_reference': raw_item['source_reference'],
        'attributes': dict(raw_item['attributes']),
    }]


class InspectGovernmentSourceTests(unittest.TestCase):
    """检查来源清单并生成提取计划。"""

    def test_inspect_creates_plan_from_workbook(self):
        """xlsx 来源经通用检查生成含中性规则的计划。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook_path = root / '名录.xlsx'
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = '机构'
            sheet.append(['机构名称', '地址', '机构类别', '机构性质'])
            sheet.append(['示例机构', '示例市甲区示例路1号', '综合机构', '公办'])
            workbook.save(workbook_path)
            workbook.close()
            manifest_path = root / 'government_source.json'
            manifest_path.write_text(
                json.dumps(build_manifest([{
                    'source_title': '机构名录',
                    'publication_date': '2026-08-01',
                    'content_url': 'https://example.gov.cn/list.xlsx',
                    'local_files': ['名录.xlsx'],
                    'derived_files': [],
                }]), ensure_ascii=False),
                encoding='utf-8',
            )
            output_path = root / 'extraction_plan.json'

            def validate_manifest(payload):
                if payload.get('stage') != 'scene_government_source':
                    raise ValueError('stage 不正确')
                return (
                    payload['city_context'],
                    payload['city_context']['subdivisions'][0],
                    payload['items'],
                )

            plan_payload, exit_code = inspect_government_source(
                manifest_path,
                output_path,
                build_terms(),
                plan_stage='scene_extraction_plan',
                validate_manifest=validate_manifest,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(plan_payload['stage'], 'scene_extraction_plan')
        self.assertEqual(plan_payload['government_source_file'], 'government_source.json')
        self.assertEqual(plan_payload['inspection_summary']['source_count'], 1)
        rules = plan_payload['items'][0]['extraction_rules']
        self.assertTrue(rules)
        rule = rules[0]
        self.assertIn('place_name_columns', rule)
        attribute_fields = {
            item['field']: item for item in rule['attribute_fields']
        }
        self.assertIn('category', attribute_fields)
        self.assertIn('nature', attribute_fields)

    def test_inspect_returns_error_code_when_validation_fails(self):
        """清单校验失败时返回退出码 1。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / 'government_source.json'
            manifest_path.write_text(
                json.dumps(build_manifest([]), ensure_ascii=False),
                encoding='utf-8',
            )

            def invalid_manifest(_payload):
                raise ValueError('来源清单不完整')

            with self.assertRaisesRegex(ValueError, '来源清单不完整'):
                inspect_government_source(
                    manifest_path,
                    root / 'plan.json',
                    build_terms(),
                    plan_stage='scene_extraction_plan',
                    validate_manifest=invalid_manifest,
                )


class ExtractGovernmentRecordsTests(unittest.TestCase):
    """执行已复核计划并提取中性记录。"""

    def write_plan(self, root, plan_payload):
        plan_path = root / 'extraction_plan.json'
        plan_path.write_text(
            json.dumps(plan_payload, ensure_ascii=False),
            encoding='utf-8',
        )
        return plan_path

    def plan_base(self):
        city_context = build_city_context()
        return {
            'stage': 'scene_extraction_plan',
            'city_context': city_context,
            'administrative_unit': city_context['subdivisions'][0],
            'government_source_file': 'government_source.json',
            'items': [],
        }

    def test_extract_executes_approved_workbook_rule(self):
        """已批准的表规则提取记录并调用场景构造回调。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook_path = root / '名录.xlsx'
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append(['机构名称', '地址', '机构类别'])
            sheet.append(['示例医院', '示例市甲区示例路1号', '综合医院'])
            workbook.save(workbook_path)
            workbook.close()
            rule = {
                'file': '名录.xlsx',
                'kind': 'sheet',
                'location': {'sheet': 'Sheet'},
                'data_start_row': 2,
                'data_end_row': None,
                'place_name_columns': [1],
                'place_name_separator': '',
                'original_address_column': 2,
                'attribute_fields': [
                    {
                        'field': 'category',
                        'column': 3,
                        'value': '',
                        'selector': '',
                        'labels': [],
                    },
                ],
                'fill_down_columns': [],
                'required_cell_values': [],
                'exclude_rows': [],
                'approved': True,
            }
            source_plan = {
                'source_title': '机构名录',
                'publication_date': '2026-08-01',
                'content_url': 'https://example.gov.cn/list.xlsx',
                'files': [
                    {'file': '名录.xlsx', 'inspection_status': 'ready'},
                ],
                'extraction_rules': [rule],
                'review_status': 'ready',
            }
            plan_payload = self.plan_base()
            plan_payload['items'] = [source_plan]
            plan_path = self.write_plan(root, plan_payload)

            records, metrics, errors = extract_government_records(
                plan_path,
                plan_stage='scene_extraction_plan',
                terms=build_terms(),
                build_address_records=build_address_record,
            )

        self.assertEqual(errors, [])
        self.assertEqual(metrics['record_count'], 1)
        self.assertEqual(records[0]['place_name'], '示例医院')
        self.assertEqual(records[0]['original_address'], '示例市甲区示例路1号')
        self.assertEqual(records[0]['attributes']['category'], '综合医院')

    def test_extract_object_list_json(self):
        """object_list 支持 JSON 数组对象。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / 'data.json'
            data_path.write_text(
                json.dumps([
                    {
                        'name': '示例机构',
                        'address': '示例市甲区示例路1号',
                        'category': '检验实验室',
                    },
                ]),
                encoding='utf-8',
            )
            rule = {
                'file': 'data.json',
                'kind': 'object_list',
                'object_format': 'json',
                'place_name_keys': ['name'],
                'original_address_keys': ['address'],
                'attribute_fields': [
                    {'field': 'category', 'keys': ['category']},
                ],
                'approved': True,
            }
            source_plan = {
                'source_title': '机构数据',
                'content_url': 'https://example.gov.cn/data.json',
                'files': [
                    {'file': 'data.json', 'inspection_status': 'ready'},
                ],
                'extraction_rules': [rule],
                'review_status': 'ready',
            }
            plan_payload = self.plan_base()
            plan_payload['items'] = [source_plan]
            plan_path = self.write_plan(root, plan_payload)

            records, metrics, errors = extract_government_records(
                plan_path,
                plan_stage='scene_extraction_plan',
                terms=build_terms(),
                build_address_records=build_address_record,
            )

        self.assertEqual(errors, [])
        self.assertEqual(metrics['record_count'], 1)
        self.assertEqual(records[0]['place_name'], '示例机构')
        self.assertEqual(records[0]['attributes']['category'], '检验实验室')
        self.assertIn('data.json', records[0]['source_reference'])

    def test_extract_html_js_assignment_cards(self):
        """html_js_assignment 支持政府门户的 JS 赋值卡片。"""
        html = """
        <script>
        var one_1 = {};
        one_1.yymc="示例医院";
        one_1.xxdz="示例市甲区示例路1号";
        one_1.jb="三级";
        one_1.dj="甲等";
        cards.push(one_1);
        </script>
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / 'cards.html'
            html_path.write_text(html, encoding='utf-8')
            rule = {
                'file': 'cards.html',
                'kind': 'object_list',
                'object_format': 'html_js_assignment',
                'assignment_id_prefix': 'one_',
                'place_name_keys': ['yymc'],
                'original_address_keys': ['xxdz'],
                'attribute_fields': [
                    {'field': 'level', 'keys': ['jb']},
                ],
                'approved': True,
            }
            source_plan = {
                'source_title': '机构卡片',
                'content_url': 'https://example.gov.cn/cards.html',
                'files': [
                    {'file': 'cards.html', 'inspection_status': 'ready'},
                ],
                'extraction_rules': [rule],
                'review_status': 'ready',
            }
            plan_payload = self.plan_base()
            plan_payload['items'] = [source_plan]
            plan_path = self.write_plan(root, plan_payload)

            records, metrics, errors = extract_government_records(
                plan_path,
                plan_stage='scene_extraction_plan',
                terms=build_terms(),
                build_address_records=build_address_record,
            )

        self.assertEqual(errors, [])
        self.assertEqual(metrics['record_count'], 1)
        self.assertEqual(records[0]['place_name'], '示例医院')
        self.assertEqual(records[0]['attributes']['level'], '三级')

    def test_skip_place_name_callback_is_applied(self):
        """skip_place_name 返回 True 的行不进入记录。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / 'data.json'
            data_path.write_text(
                json.dumps([
                    {'name': '合计', 'address': ''},
                    {'name': '示例机构', 'address': '示例市甲区示例路1号'},
                ]),
                encoding='utf-8',
            )
            rule = {
                'file': 'data.json',
                'kind': 'object_list',
                'object_format': 'json',
                'place_name_keys': ['name'],
                'original_address_keys': ['address'],
                'attribute_fields': [],
                'approved': True,
            }
            source_plan = {
                'source_title': '机构数据',
                'files': [
                    {'file': 'data.json', 'inspection_status': 'ready'},
                ],
                'extraction_rules': [rule],
                'review_status': 'ready',
            }
            plan_payload = self.plan_base()
            plan_payload['items'] = [source_plan]
            plan_path = self.write_plan(root, plan_payload)

            records, metrics, errors = extract_government_records(
                plan_path,
                plan_stage='scene_extraction_plan',
                terms=build_terms(),
                build_address_records=build_address_record,
                skip_place_name=lambda name: normalize_text(name) == '合计',
            )

        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(metrics['raw_item_count'], 2)

    def test_unapproved_rules_produce_error(self):
        """没有已批准规则的来源产生错误信息。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_plan = {
                'source_title': '无规则来源',
                'files': [],
                'extraction_rules': [],
                'review_status': 'ready',
            }
            plan_payload = self.plan_base()
            plan_payload['items'] = [source_plan]
            plan_path = self.write_plan(root, plan_payload)

            records, metrics, errors = extract_government_records(
                plan_path,
                plan_stage='scene_extraction_plan',
                terms=build_terms(),
                build_address_records=build_address_record,
            )

        self.assertEqual(records, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('没有已批准的提取规则', errors[0])
        self.assertEqual(metrics['error_count'], 1)


class EngineNeutralityTests(unittest.TestCase):
    """引擎源码不得包含场景词。"""

    def test_engine_source_has_no_scenario_words(self):
        engine_source = (
            Path(__file__).resolve().parents[1]
            / 'src/query_city_core/official/extract/engine.py'
        ).read_text(encoding='utf-8')
        for scenario_word in (
            'school', 'university', 'medical', 'hospital', 'institution',
        ):
            self.assertNotIn(scenario_word, engine_source)


if __name__ == '__main__':
    unittest.main()
