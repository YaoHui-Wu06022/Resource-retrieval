"""官方来源提取通用引擎测试。"""

import tempfile
import unittest
from pathlib import Path

from query_city_core.official.extract import (
    AttributeTerm,
    FieldTerms,
    build_source_reference,
    infer_html_key_value_rule,
    infer_table_rule,
    normalize_header,
    read_key_value_field,
)


def build_generic_terms():
    """构造非学校场景词表，验证引擎不绑定学校语义。"""
    return FieldTerms(
        place_headers=('机构名称', '单位名称'),
        exact_place_headers=('名称',),
        address_headers=('地址', '详细地址'),
        attribute_terms=(
            AttributeTerm('category', headers=('机构类型',), label_text='机构类别'),
            AttributeTerm('nature', headers=('机构性质',), label_text='机构性质'),
        ),
        place_marker_pattern=r'(?:医院|中心|站)',
        address_marker_pattern=r'(?:路|街|号|园区)',
        excluded_place_label_pattern=r'机构类别|上级单位',
    )


class OfficialExtractRulesTest(unittest.TestCase):
    """验证表头推断函数可接受任意场景词表。"""

    @staticmethod
    def field_entry(rule, field):
        """从 attribute_fields 中取指定字段。"""
        return next(
            item for item in rule['attribute_fields']
            if item['field'] == field
        )

    def test_infer_table_rule_uses_custom_terms(self):
        """医院/机关类表头应能推断出机构名称与地址列。"""
        rows = [
            ['机构名称', '地址', '机构类型'],
            ['示例医院', '甲区乙路1号', '医院'],
        ]
        rule = infer_table_rule(
            rows, '名录.xlsx', 'sheet', {'sheet': '医院'}, build_generic_terms()
        )
        self.assertIsNotNone(rule)
        self.assertEqual(rule['place_name_columns'], [1])
        self.assertEqual(rule['original_address_column'], 2)
        self.assertEqual(self.field_entry(rule, 'category')['column'], 3)
        self.assertEqual(self.field_entry(rule, 'nature')['column'], None)
        self.assertEqual(rule['data_start_row'], 2)

    def test_infer_html_key_value_rule_uses_custom_terms(self):
        """纵向键值表同样使用场景词表。"""
        rows = [
            ['机构名称', '示例医院'],
            ['地址', '甲区乙路1号'],
            ['机构性质', '公立'],
        ]
        rule = infer_html_key_value_rule(
            rows, '详情.html', build_generic_terms()
        )
        self.assertIsNotNone(rule)
        self.assertEqual(rule['place_name_labels'], ['机构名称'])
        self.assertEqual(rule['original_address_labels'], ['地址'])
        self.assertEqual(
            self.field_entry(rule, 'nature')['labels'],
            ['机构性质'],
        )

    def test_normalize_header_and_key_value_field(self):
        """表头与键值标签统一清洗。"""
        self.assertEqual(normalize_header('机构名称：'), '机构名称')
        fields = {'机构名称': '示例医院', '地址': '甲路1号'}
        self.assertEqual(
            read_key_value_field(fields, ('机构名称',), ('单位名称',)),
            '示例医院',
        )

    def test_build_source_reference_is_generic(self):
        """来源定位组合不包含学校语义。"""
        source = {'content_url': 'https://example.gov.cn/a', 'title': 'x'}
        self.assertEqual(
            build_source_reference(source, '名录.csv | sheet 1'),
            'https://example.gov.cn/a | 名录.csv | sheet 1',
        )


if __name__ == '__main__':
    unittest.main()
