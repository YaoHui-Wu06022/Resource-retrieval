"""官方来源提取通用引擎：表头规则推断与通用提取工具。"""

from .extract_utils import (
    build_source_reference,
    extract_text_segments,
    is_table_location_match,
    normalize_key_value_label,
    read_key_value_field,
    validate_positive_index,
)
from .engine import (
    extract_government_records,
    inspect_government_source,
)
from .rules import (
    AttributeTerm,
    FieldTerms,
    collect_repeated_html_candidates,
    consolidate_html_key_value_rules,
    infer_html_key_value_rule,
    infer_table_rule,
    inspect_source_file,
    normalize_header,
    read_table_cell,
    resolve_source_path,
)

__all__ = (
    'AttributeTerm',
    'FieldTerms',
    'build_source_reference',
    'collect_repeated_html_candidates',
    'consolidate_html_key_value_rules',
    'extract_government_records',
    'extract_text_segments',
    'infer_html_key_value_rule',
    'infer_table_rule',
    'inspect_government_source',
    'inspect_source_file',
    'is_table_location_match',
    'normalize_header',
    'normalize_key_value_label',
    'read_key_value_field',
    'read_table_cell',
    'resolve_source_path',
    'validate_positive_index',
)
