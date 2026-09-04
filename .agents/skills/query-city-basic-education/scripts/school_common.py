"""基础教育学校记录构造、规范化与去重的公共模块。"""

import re
from datetime import date
from typing import Any

from query_city_core.address.common import SUBDIVISION_SCOPE_SUBDIVISION
from query_city_core.official.extract import (
    AttributeTerm,
    FieldTerms,
    read_table_cell,
)
from query_city_core.official.readers import normalize_text


PLACE_HEADERS = (
    '学校名称', '幼儿园名称', '园所名称', '机构名称', '单位名称', '校名',
)
EXACT_PLACE_HEADERS = ('学校', '名称')
ADDRESS_HEADERS = (
    '学校地址', '办学地址', '园区地址', '园所地址',
    '详细地址', '校址', '地址',
)
SCHOOL_TYPE_HEADERS = (
    '学校类型', '办学类型', '办学层次', '主体学校办学类型名称',
)
SCHOOL_NATURE_HEADERS = ('学校性质', '办学性质', '办园性质')

SCHOOL_FIELD_TERMS = FieldTerms(
    place_headers=PLACE_HEADERS,
    exact_place_headers=EXACT_PLACE_HEADERS,
    address_headers=ADDRESS_HEADERS,
    attribute_terms=(
        AttributeTerm(
            'school_type',
            headers=SCHOOL_TYPE_HEADERS,
            label_text='学校类别',
        ),
        AttributeTerm(
            'school_nature',
            headers=SCHOOL_NATURE_HEADERS,
            label_text='学校性质',
            fill_down=True,
        ),
    ),
    place_marker_pattern=r'(?:学校|幼儿园|小学|中学|校区|教学点)',
    address_marker_pattern=r'(?:路|街|巷|大道|公路|村|号|园区|镇|区|县)',
    excluded_place_label_pattern=r'学校类别|学校性质|上级主管部门',
)

NON_RECORD_NAME_PATTERN = re.compile(
    r'^(?:更新时间|更新日期|数据截止|截至日期|填表|制表|备注|说明|'
    r'招生计划|计划招生|合计|总计)'
)


def classify_school_type_from_presence(
    table_row: list[str], column_mappings: list[dict[str, Any]]
) -> str:
    """根据非零招生人数列推断学校类型，不决定是否保留学校。"""
    school_types = []
    for column_mapping in column_mappings:
        cell_value = read_table_cell(table_row, column_mapping['column'])
        if cell_value not in {'', '0', '0.0', '/', '-', '—'}:
            school_types.append(column_mapping['value'])
    return '、'.join(dict.fromkeys(school_types))


def build_school_record(
    place_name: str,
    original_address: str,
    school_type: str,
    school_nature: str,
    source_record: dict[str, Any],
    source_location: str,
    administrative_unit: str,
    address_ambiguity: str = '',
) -> dict[str, Any]:
    """生成公共地址输入记录。"""
    normalized_place_name = normalize_place_name_text(place_name)
    normalized_school_type = (
        infer_school_type_from_stage_name(normalized_place_name)
        or infer_school_type_from_name_marker(normalized_place_name)
        or normalize_school_type(school_type)
    )
    attributes = {
        'administrative_unit': administrative_unit,
        'subdivision_scope': SUBDIVISION_SCOPE_SUBDIVISION,
        'school_type': normalized_school_type,
        'poi_name_aliases': build_poi_name_aliases(
            normalized_place_name,
            normalized_school_type,
        ),
        'school_nature': normalize_school_nature(school_nature),
        'publication_date': resolve_publication_date(
            source_record.get('publication_date')
        ),
    }
    if normalize_text(address_ambiguity):
        attributes['address_ambiguity'] = normalize_text(
            address_ambiguity
        )
    return {
        'place_name': normalized_place_name,
        'original_address': normalize_text(original_address),
        'source_nature': 'government_information',
        'address_mode': 'government_list',
        'source_reference': source_location,
        'attributes': attributes,
    }


def build_records_for_locations(
    place_name: str,
    original_address: str,
    school_type: str,
    school_nature: str,
    source_record: dict[str, Any],
    source_location: str,
    administrative_unit: str,
) -> list[dict[str, Any]]:
    """拆分明确校区地址并为每个地点生成学校记录。"""
    records = []
    campus_locations = split_explicit_campus_addresses(
        place_name, original_address
    )
    normalized_place_name = normalize_text(place_name)
    normalized_address = normalize_text(original_address)
    ambiguity_note = ''
    if (
        len(campus_locations) == 1
        and campus_locations[0] == (
            normalized_place_name, normalized_address
        )
        and normalized_address
        and CAMPUS_AMBIGUITY_HINT_PATTERN.search(normalized_address)
    ):
        ambiguity_note = f'校区边界无法确定：{normalized_address}'
    for location_index, (location_name, location_address) in enumerate(
        campus_locations, start=1
    ):
        record_location = source_location
        if len(campus_locations) > 1:
            record_location += f' | address {location_index}'
        records.append(build_school_record(
            location_name,
            location_address,
            school_type,
            school_nature,
            source_record,
            record_location,
            administrative_unit,
            ambiguity_note if location_index == 1 else '',
        ))
    return records


def is_non_school_record_name(place_name: str) -> bool:
    """识别表尾说明、合计和更新时间。"""
    normalized = normalize_text(place_name)
    if NON_RECORD_NAME_PATTERN.search(normalized):
        return True
    return bool(re.fullmatch(r'\d[\d\s]*', normalized))


CAMPUS_SUFFIX_WORDS = (
    '校区', '园区', '分园', '教学点', '分教点',
    '分校', '正校', '本校', '总校', '总园',
)
CAMPUS_BARE_UNITS = ('总校', '分校', '正校', '本校', '总园')
CAMPUS_STAGE_WORDS = ('校本部', '中学部', '初中部', '小学部', '高中部')
CAMPUS_QUALIFIED_WORDS = ('校区', '校园', '分园', '园区', '教学点', '分教点')
CAMPUS_BANNED_CHARS = r'\s：:（）()号；;，,。.、/／'
CAMPUS_BANNED_CHARS_WITH_ROAD = CAMPUS_BANNED_CHARS + r'路街巷道'
ADDRESS_TRIM_CHARS = '；;，,。.、/／ '
PAREN_ADDRESS_TRIM_CHARS = '；;，, '
CAMPUS_SUFFIX_UNIT_PATTERN = '|'.join(CAMPUS_SUFFIX_WORDS)
CAMPUS_BARE_UNIT_PATTERN = '|'.join(CAMPUS_BARE_UNITS)
CAMPUS_STAGE_WORDS_PATTERN = '|'.join(CAMPUS_STAGE_WORDS)
CAMPUS_DELIMITER_PATTERN = (
    r'\s*(?:地址)?\s*(?:[：:]|[—－–-]|\s+)'
)
EXPLICIT_CAMPUS_LABEL = (
    rf'(?:[^{CAMPUS_BANNED_CHARS}]{{1,20}}'
    rf'(?:{CAMPUS_SUFFIX_UNIT_PATTERN})'
    rf'|{CAMPUS_STAGE_WORDS_PATTERN}|{CAMPUS_BARE_UNIT_PATTERN}'
    r'|校本部(?:初中部|小学部|高中部))'
)
RESTRICTED_CAMPUS_LABEL = (
    rf'(?:[^{CAMPUS_BANNED_CHARS_WITH_ROAD}]{{1,20}}'
    rf'(?:{CAMPUS_SUFFIX_UNIT_PATTERN})'
    rf'|{CAMPUS_STAGE_WORDS_PATTERN}|{CAMPUS_BARE_UNIT_PATTERN}'
    r'|校本部(?:初中部|小学部|高中部))'
)
CAMPUS_PREFIX_PATTERN = re.compile(
    rf'(?P<campus>{RESTRICTED_CAMPUS_LABEL}){CAMPUS_DELIMITER_PATTERN}'
)
CAMPUS_PREFIX_FULL_PATTERN = re.compile(
    rf'(?P<campus>{EXPLICIT_CAMPUS_LABEL}){CAMPUS_DELIMITER_PATTERN}'
)
CAMPUS_SUFFIX_PATTERN = re.compile(
    rf'^(?P<address>.+?)[（(](?P<campus>{EXPLICIT_CAMPUS_LABEL})[）)]$'
)
CAMPUS_SUFFIX_SEGMENT_PATTERN = re.compile(
    rf'(?P<address>.+?)[（(](?P<campus>{EXPLICIT_CAMPUS_LABEL})[）)]'
)
CAMPUS_PAREN_PREFIX_PATTERN = re.compile(
    rf'[（(](?P<campus>{EXPLICIT_CAMPUS_LABEL})[）)]\s*'
)
CAMPUS_AMBIGUITY_UNIT_PATTERN = '|'.join(
    CAMPUS_SUFFIX_WORDS + CAMPUS_STAGE_WORDS
)
CAMPUS_AMBIGUITY_HINT_PATTERN = re.compile(
    rf'(?:[（(].{{0,20}}(?:{CAMPUS_AMBIGUITY_UNIT_PATTERN})[）)]'
    rf'|(?:{CAMPUS_AMBIGUITY_UNIT_PATTERN})'
    rf'{CAMPUS_DELIMITER_PATTERN})'
)
GRADE_NOTE_PATTERN = re.compile(
    r'[（(](?:初|高|小|一|二|三|四|五|六|七|八|九|年级|至|、|，|,|\s)+[）)]$'
)
CHINESE_NAME_SPACE_PATTERN = re.compile(
    r'(?<=[\u3400-\u9fff（）])\s+(?=[\u3400-\u9fff（）])'
)
SCHOOL_TYPE_LABEL_PATTERN = re.compile(
    r'^[▪•·\-—\s]*(?:学校)?(?:类别|类型|办学层次)\s*[：:]\s*'
)
STANDARD_SCHOOL_TYPES = {
    '幼儿园',
    '小学',
    '初中',
    '高中',
    '完全中学',
    '特殊教育学校',
    '中等职业学校',
    '职业高级中学',
    '技工院校',
    '成人中等学校',
    '专门学校',
}
SCHOOL_TYPE_STAGES = {
    '完全中学': ('初中', '高中'),
    '九年一贯制学校': ('小学', '初中'),
    '十二年一贯制学校': ('小学', '初中', '高中'),
    '十五年一贯制学校': ('幼儿园', '小学', '初中', '高中'),
}
BASIC_SCHOOL_STAGES = ('幼儿园', '小学', '初中', '高中')
SCHOOL_STAGE_SUFFIXES = (
    ('高中部', '高中'),
    ('初中部', '初中'),
    ('小学部', '小学'),
    ('中学部', ('初中', '高中')),
)
CAMPUS_QUALIFIED_NAME_PATTERN = re.compile(
    '|'.join(CAMPUS_QUALIFIED_WORDS)
)
STAGE_NAME_FORMAT_PATTERN = re.compile(r'[（()）\[\]]')
MAX_CAMPUS_SPLIT_DEPTH = 5


def normalize_school_type_part(school_type_part: str) -> str:
    """规范单个学校类型或学段名称。"""
    school_type_part = normalize_text(school_type_part)
    year_match = re.search(
        r'([零〇一二三四五六七八九十百\d]+)年(?:一贯)?制(?:学校)?',
        school_type_part,
    )
    if year_match:
        return f'{year_match.group(1)}年一贯制学校'
    mappings = (
        (r'职业高级中学|职业高中', '职业高级中学'),
        (r'中等职业|中职|中等专业', '中等职业学校'),
        (r'特殊教育|培智', '特殊教育学校'),
        (r'技师学院|技工学校', '技工院校'),
        (r'成人中等', '成人中等学校'),
        (r'完全中学|完中', '完全中学'),
        (r'初级中学|初中', '初中'),
        (r'高级中学|普通高中|高中', '高中'),
    )
    return next(
        (
            normalized
            for pattern, normalized in mappings
            if re.search(pattern, school_type_part)
        ),
        school_type_part,
    )


def normalize_school_type(school_type_text: Any) -> str:
    """规范官方学校类型并保留无法识别的原文。"""
    normalized_text = SCHOOL_TYPE_LABEL_PATTERN.sub(
        '', normalize_text(school_type_text)
    )
    parenthesized_parts = re.findall(r'[（(](.*?)[）)]', normalized_text)
    for parenthesized_part in reversed(parenthesized_parts):
        normalized_part = normalize_school_type_part(parenthesized_part)
        if (
            normalized_part in STANDARD_SCHOOL_TYPES
            or re.fullmatch(r'.+年一贯制学校', normalized_part)
        ):
            return normalized_part
    normalized_text = re.sub(r'[（(].*?[）)]', '', normalized_text)
    school_type_parts = [
        school_type_part
        for school_type_part in re.split(r'[、，,;/；]+', normalized_text)
        if normalize_text(school_type_part)
    ]
    return '、'.join(dict.fromkeys(
        normalize_school_type_part(school_type_part)
        for school_type_part in school_type_parts
    ))


def infer_school_type_from_stage_name(place_name: Any) -> str:
    """从明确的小学部、初中部或高中部名称取得单条记录学段。"""
    stage_match = re.search(
        r'(小学部|中学部|初中部|高中部)$',
        normalize_place_name_text(place_name),
    )
    return {
        '小学部': '小学',
        '中学部': '初中',
        '初中部': '初中',
        '高中部': '高中',
    }.get(stage_match.group(1) if stage_match else '', '')


def infer_school_type_from_name_marker(place_name: Any) -> str:
    """从校名中明确的官方一贯制标记推断学校类型。"""
    normalized_name = normalize_place_name_text(place_name)
    for marker, school_type in (
        ('九年一贯制', '九年一贯制学校'),
        ('十二年一贯制', '十二年一贯制学校'),
        ('十五年一贯制', '十五年一贯制学校'),
    ):
        if re.search(rf'[（(]{re.escape(marker)}[）)]', normalized_name):
            return school_type
    return ''


def normalize_stage_name(value: Any) -> str:
    """压缩学校名称并移除用于名称比对的括号。"""
    return STAGE_NAME_FORMAT_PATTERN.sub(
        '', normalize_place_name_text(value)
    )


def split_school_stage_suffix(value: Any) -> tuple[str, Any]:
    """从名称末尾拆分学部后缀，返回正文与覆盖学段。"""
    cleaned = normalize_stage_name(value)
    for suffix, stage in SCHOOL_STAGE_SUFFIXES:
        if cleaned.endswith(suffix):
            return cleaned[:-len(suffix)], stage
    return cleaned, ''


def extract_single_school_stage(school_type: Any) -> str:
    """记录类型只覆盖一个基础学段时返回该学段，否则返回空字符串。"""
    stages = {
        stage
        for stage in str(school_type or '').split('、')
        if stage in {'小学', '初中', '高中'}
    }
    return next(iter(stages)) if len(stages) == 1 else ''


def stage_suffix_compatible(stage_group: Any, record_stage: str) -> bool:
    """判断学部后缀覆盖的学段与记录类型学段一致。"""
    if isinstance(stage_group, tuple):
        return record_stage in stage_group
    return stage_group == record_stage


def build_poi_name_aliases(place_name: Any, school_type: Any) -> list[str]:
    """为单学段政府记录生成允许的 POI 全名别名。"""
    normalized = normalize_stage_name(place_name)
    if not normalized or CAMPUS_QUALIFIED_NAME_PATTERN.search(normalized):
        return []
    record_stage = extract_single_school_stage(school_type)
    if not record_stage:
        return []
    base, place_stage = split_school_stage_suffix(normalized)
    if place_stage and not stage_suffix_compatible(
        place_stage, record_stage
    ):
        return []
    if not base:
        return []
    aliases = []
    if place_stage:
        aliases.append(base)
    for suffix, stage_group in SCHOOL_STAGE_SUFFIXES:
        if not stage_suffix_compatible(stage_group, record_stage):
            continue
        alias = base + suffix
        if alias != normalized and alias not in aliases:
            aliases.append(alias)
    return aliases


def normalize_school_nature(school_nature_text: Any) -> str:
    """把明确办学性质规范为公办或民办，其余保留原文。"""
    normalized_nature = normalize_text(school_nature_text)
    if '公办' in normalized_nature:
        return '公办'
    if '民办' in normalized_nature:
        return '民办'
    return normalized_nature


def merge_school_types(current_type: str, incoming_type: str) -> str:
    """按学段去重合并学校类型，保留官方类型标签。"""
    school_types = list(dict.fromkeys(
        school_type
        for school_type in f'{current_type}、{incoming_type}'.split('、')
        if school_type
    ))
    retained = []
    for index, school_type in enumerate(school_types):
        type_stages = school_type_stages(school_type)
        other_stages = {
            stage
            for other_index, other_type in enumerate(school_types)
            if other_index != index
            for stage in school_type_stages(other_type)
        }
        if type_stages and set(type_stages).issubset(other_stages):
            continue
        retained.append(school_type)
    return '、'.join(retained)


def school_type_stages(school_type: str) -> tuple[str, ...]:
    """返回学校类型覆盖的学段；不可拆解的官方类型返回空元组。"""
    return SCHOOL_TYPE_STAGES.get(
        school_type,
        (school_type,) if school_type in BASIC_SCHOOL_STAGES else (),
    )


def resolve_publication_date(publication_date: Any) -> str:
    """优先使用来源发布日期，缺失时返回当天日期。"""
    return normalize_text(publication_date) or date.today().isoformat()


def normalize_place_name_text(place_name: Any) -> str:
    """移除学校中文名称内部由断行或提取产生的空格。"""
    return CHINESE_NAME_SPACE_PATTERN.sub('', normalize_text(place_name))


def append_campus_name(place_name: str, campus_name: str) -> str:
    """把明确校区名称拼接到学校名称。"""
    place_name = normalize_text(place_name)
    campus_name = normalize_text(campus_name).strip(ADDRESS_TRIM_CHARS)
    return place_name if campus_name in place_name else place_name + campus_name


def split_explicit_campus_addresses(
    place_name: str, original_address: str
) -> list[tuple[str, str]]:
    """拆分带明确校区标签的单行或多行地址，嵌套校区标签逐级拆分。"""

    def split_address_once(
        current_name: str, current_address: str
    ) -> list[tuple[str, str]]:
        """按现有校区标签规则对单个文本片段执行一遍拆分。"""
        raw_lines = [
            normalize_text(address_line)
            for address_line in str(current_address).splitlines()
            if normalize_text(address_line)
        ]
        lines = []
        locations = []
        for line in raw_lines:
            parts = [
                normalize_text(address_part)
                for address_part in re.split(r'[/／]', line)
            ]
            matched_parts = [
                part for part in parts
                if CAMPUS_SUFFIX_PATTERN.fullmatch(part)
            ]
            if len(parts) <= 1 or not matched_parts:
                lines.append(line)
                continue
            for part in parts:
                suffix_match = CAMPUS_SUFFIX_PATTERN.fullmatch(part)
                if suffix_match:
                    locations.append((
                        append_campus_name(
                            current_name, suffix_match.group('campus')
                        ),
                        suffix_match.group('address'),
                    ))
                else:
                    locations.append((current_name, part))
        for line in lines:
            matches = list(CAMPUS_PREFIX_PATTERN.finditer(line))
            if not (matches and matches[0].start() == 0):
                full_matches = list(
                    CAMPUS_PREFIX_FULL_PATTERN.finditer(line)
                )
                if full_matches and full_matches[0].start() == 0:
                    matches = full_matches
            if matches and matches[0].start() == 0:
                for index, match in enumerate(matches):
                    end = (
                        matches[index + 1].start()
                        if index + 1 < len(matches)
                        else len(line)
                    )
                    address = GRADE_NOTE_PATTERN.sub(
                        '', line[match.end():end]
                    ).strip(ADDRESS_TRIM_CHARS)
                    if not address:
                        return [(current_name, current_address)]
                    locations.append((
                        append_campus_name(
                            current_name, match.group('campus')
                        ),
                        address,
                    ))
                continue
            matches = list(CAMPUS_PAREN_PREFIX_PATTERN.finditer(line))
            if matches and matches[0].start() == 0:
                for index, match in enumerate(matches):
                    end = (
                        matches[index + 1].start()
                        if index + 1 < len(matches)
                        else len(line)
                    )
                    address = normalize_text(
                        line[match.end():end].strip(PAREN_ADDRESS_TRIM_CHARS)
                    )
                    if not address:
                        return [(current_name, current_address)]
                    locations.append((
                        append_campus_name(
                            current_name, match.group('campus')
                        ),
                        address,
                    ))
                continue
            suffix_segments = list(
                CAMPUS_SUFFIX_SEGMENT_PATTERN.finditer(line)
            )
            if (
                len(suffix_segments) > 1
                and ''.join(
                    match.group(0) for match in suffix_segments
                ) == line
            ):
                locations.extend((
                    append_campus_name(
                        current_name, match.group('campus')
                    ),
                    normalize_text(match.group('address')).strip(
                        ADDRESS_TRIM_CHARS
                    ),
                ) for match in suffix_segments)
                continue
            suffix_match = CAMPUS_SUFFIX_PATTERN.fullmatch(line)
            if suffix_match is None:
                return [(current_name, current_address)]
            locations.append((
                append_campus_name(
                    current_name, suffix_match.group('campus')
                ),
                suffix_match.group('address'),
            ))
        return locations or [(current_name, current_address)]

    def expand_nested_campuses(
        current_name: str,
        current_address: str,
        depth: int,
    ) -> list[tuple[str, str]]:
        """逐级拆分仍含校区标签的地址片段，达到深度上限后原样保留。"""
        if depth >= MAX_CAMPUS_SPLIT_DEPTH or not current_address:
            return [(current_name, current_address)]
        parsed_locations = split_address_once(
            current_name, current_address
        )
        if (
            len(parsed_locations) == 1
            and parsed_locations[0] == (current_name, current_address)
        ):
            return parsed_locations
        expanded_locations = []
        for child_name, child_address in parsed_locations:
            expanded_locations.extend(expand_nested_campuses(
                child_name, child_address, depth + 1
            ))
        return expanded_locations

    return expand_nested_campuses(place_name, original_address, 0)


def deduplicate_school_records(
    school_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """按学校名称和原始地址合并记录，保留最新来源并补全学校类型。"""
    unique_records = []
    record_indexes = {}
    for school_record in school_records:
        record_key = (
            school_record['place_name'], school_record['original_address']
        )
        if record_key not in record_indexes:
            record_indexes[record_key] = len(unique_records)
            unique_records.append(school_record)
            continue
        record_index = record_indexes[record_key]
        current_record = unique_records[record_index]
        current_type = current_record['attributes']['school_type']
        incoming_type = school_record['attributes']['school_type']
        if (
            school_record['attributes'].get('publication_date', '')
            > current_record['attributes'].get('publication_date', '')
        ):
            current_record = school_record
            unique_records[record_index] = current_record
        merged_type = merge_school_types(
            current_type, incoming_type
        )
        current_record['attributes']['school_type'] = merged_type
        current_record['attributes']['poi_name_aliases'] = (
            build_poi_name_aliases(
                current_record['place_name'],
                merged_type,
            )
        )
    return unique_records, len(school_records) - len(unique_records)


def school_base_identity(place_name: Any) -> str:
    """返回去除末尾括号校区/园区后的学校基础名称。"""
    normalized = normalize_place_name_text(place_name)
    campus_match = CAMPUS_SUFFIX_PATTERN.fullmatch(normalized)
    return campus_match.group('address') if campus_match else normalized


def fill_missing_school_type_from_siblings(
    school_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """用同校其他校区的唯一非空类型回填空类型记录。"""
    groups: dict[tuple[str, str, str], list[int]] = {}
    for record_index, school_record in enumerate(school_records):
        attributes = school_record.get('attributes') or {}
        source_origin = str(
            school_record.get('source_reference') or ''
        ).split(' | ', 1)[0]
        group_key = (
            str(attributes.get('administrative_unit') or '').strip(),
            school_base_identity(school_record.get('place_name') or ''),
            source_origin,
        )
        groups.setdefault(group_key, []).append(record_index)
    for record_indexes in groups.values():
        known_types = []
        for record_index in record_indexes:
            school_type = str(
                (school_records[record_index].get('attributes') or {}).get(
                    'school_type'
                ) or ''
            ).strip()
            if school_type:
                known_types.append(school_type)
        unique_types = list(dict.fromkeys(known_types))
        if len(unique_types) != 1:
            continue
        for record_index in record_indexes:
            attributes = school_records[record_index].get('attributes') or {}
            if attributes.get('school_type'):
                continue
            attributes['school_type'] = unique_types[0]
            attributes['poi_name_aliases'] = build_poi_name_aliases(
                school_records[record_index].get('place_name') or '',
                unique_types[0],
            )
    return school_records


def fill_missing_original_address_from_siblings(
    school_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """用同校区记录的唯一官方地址回填空地址记录。"""
    groups: dict[tuple[str, str], list[int]] = {}
    for record_index, school_record in enumerate(school_records):
        attributes = school_record.get('attributes') or {}
        group_key = (
            str(attributes.get('administrative_unit') or '').strip(),
            normalize_place_name_text(
                school_record.get('place_name') or ''
            ),
        )
        groups.setdefault(group_key, []).append(record_index)
    for record_indexes in groups.values():
        addresses = []
        for record_index in record_indexes:
            address = str(
                school_records[record_index].get('original_address') or ''
            ).strip()
            if address:
                addresses.append(address)
        unique_addresses = list(dict.fromkeys(addresses))
        if len(unique_addresses) != 1:
            continue
        for record_index in record_indexes:
            if school_records[record_index].get('original_address'):
                continue
            school_records[record_index]['original_address'] = (
                unique_addresses[0]
            )
    return school_records
