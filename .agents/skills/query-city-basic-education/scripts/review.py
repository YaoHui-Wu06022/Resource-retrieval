"""v2 复核辅助：按文件/表配置精确批准提取计划规则。"""

import json
import sys
from pathlib import Path
from typing import Any

from query_city_core.official.readers import load_source_tables


def _set_attr(rule: dict, field_name: str, column: int | None, value: str) -> None:
    fields = rule.setdefault('attribute_fields', [])
    for field in fields:
        if field.get('field') == field_name:
            field['column'] = column
            field['value'] = value
            field['selector'] = ''
            return
    fields.append({
        'field': field_name,
        'column': column,
        'value': value,
        'selector': '',
        'labels': [],
    })


def _apply_type_mapping(rule: dict, mapping: dict[str, str]) -> None:
    """把指定学段列的原始文本按映射改写为规范类型。"""
    for field in rule.get('attribute_fields', []):
        if (
            field.get('field') == 'school_type'
            and field.get('column') is not None
        ):
            labels = field.setdefault('labels', [])
            if labels and isinstance(labels[0], dict):
                return
            for source_text, target_text in mapping.items():
                labels.append({
                    'value': source_text,
                    'replace_with': target_text,
                })
            return


def _apply_spec(rule: dict, spec: dict) -> None:
    if 'name_cols' in spec:
        rule['place_name_columns'] = spec['name_cols']
    if 'addr_col' in spec:
        rule['original_address_column'] = spec['addr_col']
    if 'required' in spec:
        rule['required_cell_values'] = spec['required']
    if 'fill_down' in spec:
        rule['fill_down_columns'] = spec['fill_down']
    if 'exclude_rows' in spec:
        rule['exclude_rows'] = spec['exclude_rows']
    if 'header_row' in spec:
        rule['header_row'] = spec['header_row']
    if 'data_start_row' in spec:
        rule['data_start_row'] = spec['data_start_row']
    fixed_type = spec.get('fixed_type')
    type_col = spec.get('type_col')
    nature_col = spec.get('nature_col')
    fixed_nature = spec.get('fixed_nature')
    if fixed_type:
        _set_attr(rule, 'school_type', None, fixed_type)
    elif type_col is not None:
        _set_attr(rule, 'school_type', type_col, '')
    if nature_col is not None:
        _set_attr(rule, 'school_nature', nature_col, '')
    if fixed_nature:
        _set_attr(rule, 'school_nature', None, fixed_nature)
    if spec.get('type_mapping'):
        _apply_type_mapping(rule, spec['type_mapping'])


def _make_rule(
    file_name: str,
    spec: dict,
    location_key: str,
) -> dict[str, Any]:
    location = spec['location']
    if location_key == 'page':
        location_value: dict[str, Any] = {'page': location}
    else:
        location_value = {'table_index': location}
    return {
        'file': file_name,
        'kind': spec.get('kind', 'vision_table'),
        'location': location_value,
        'header_row': spec.get('header_row', 0),
        'data_start_row': spec.get('data_start_row', 1),
        'data_end_row': None,
        'place_name_columns': spec.get('name_cols') or [1],
        'place_name_separator': '',
        'original_address_column': spec.get('addr_col'),
        'attribute_fields': [],
        'fill_down_columns': [],
        'required_cell_values': [],
        'exclude_rows': [],
        'approved': False,
    }


def _load_pdf_tables_by_location(
    plan_path: Path, item: dict
) -> dict[tuple[int, int], dict]:
    pdf_rule = next(
        (
            rule
            for rule in item.get('extraction_rules', [])
            if rule.get('kind') == 'pdf_table'
        ),
        None,
    )
    if pdf_rule is None:
        return {}
    pdf_path = Path(plan_path).parent / pdf_rule['file']
    if not pdf_path.exists():
        return {}
    tables, _ = load_source_tables(pdf_path)
    return {
        (
            table.get('location', {}).get('page'),
            table.get('location', {}).get('table_index'),
        ): table
        for table in tables
    }


def _item_matches_file(item: dict, file_name: str) -> bool:
    if any(file_name in rule.get('file', '') for rule in item.get('extraction_rules', [])):
        return True
    for key in ('local_files', 'derived_files'):
        for entry in item.get(key) or []:
            if file_name in entry:
                return True
    return any(
        file_name in source_file.get('file', '')
        for source_file in item.get('files') or []
    )


def main() -> None:
    plan_path, config_path = Path(sys.argv[1]), Path(sys.argv[2])
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    config = json.loads(config_path.read_text(encoding='utf-8'))
    district = config['district']

    tables_by_location: dict[tuple[int, int], dict] = {}
    for item in plan.get('items', []):
        if '报考指南' not in item.get('source_title', ''):
            continue
        if item.get('extraction_rules'):
            tables_by_location = _load_pdf_tables_by_location(plan_path, item)
            break

    for item in plan.get('items', []):
        title = item.get('source_title', '')
        if '报考指南' in title:
            kept = []
            for rule in item.get('extraction_rules', []):
                if rule.get('kind') != 'pdf_table':
                    continue
                location = rule.get('location', {})
                key = (location.get('page'), location.get('table_index'))
                table = tables_by_location.get(key)
                if table is None:
                    continue
                has_district = any(
                    len(cells) >= 5 and cells[4] == district
                    for row in table.get('rows', [])
                    for cells in [[str(cell).strip() for cell in row]]
                )
                if not has_district:
                    continue
                rule['place_name_columns'] = [2]
                rule['original_address_column'] = 6
                rule['required_cell_values'] = [
                    {'column': 5, 'value': district}
                ]
                _set_attr(rule, 'school_type', 4, '')
                _set_attr(rule, 'school_nature', 3, '')
                rule['approved'] = True
                kept.append(rule)
            item['extraction_rules'] = kept
            item['review_status'] = 'ready'
            print('报考指南规则已批准：', len(kept))
            continue

        for file_spec in config.get('files', []):
            if not _item_matches_file(item, file_spec['file']):
                continue
            location_key = file_spec.get('location_key', 'table_index')
            existing = {
                (
                    rule.get('kind'),
                    rule.get('location', {}).get(location_key),
                ): rule
                for rule in item.get('extraction_rules', [])
                if file_spec['file'] in rule.get('file', '')
            }
            kept = []
            for spec in file_spec.get('rules', []):
                key = (spec.get('kind'), spec.get('location'))
                rule = existing.get(key)
                if spec.get('drop'):
                    continue
                if rule is None:
                    rule = _make_rule(
                        file_spec['file'], spec, location_key
                    )
                    item.setdefault('extraction_rules', []).append(rule)
                _apply_spec(rule, spec)
                rule['approved'] = True
                kept.append(rule)
            for rule in item.get('extraction_rules', []):
                if (
                    file_spec['file'] in rule.get('file', '')
                    and rule not in kept
                    and not rule.get('approved')
                ):
                    item['extraction_rules'].remove(rule)
            item['review_status'] = 'ready'
            print(
                '文件规则已复核：',
                file_spec['file'],
                '批准',
                len(kept),
            )

    for item in plan.get('items', []):
        if item.get('review_status') != 'ready':
            item['extraction_rules'] = []
            item['review_status'] = 'ready'

    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print('plan updated:', plan_path)


if __name__ == '__main__':
    main()
