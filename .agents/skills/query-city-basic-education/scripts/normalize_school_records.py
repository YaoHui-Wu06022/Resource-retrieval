"""规范、拆分并精确去重基础教育学校记录。"""

import re
from datetime import date
from typing import Any

from source_readers import normalize_text


EXPLICIT_CAMPUS_LABEL = (
    r'(?:校本部|中学部|初中部|小学部|高中部|总校|分校|总园|'
    r'校本部(?:初中部|小学部|高中部)|'
    r'[^\s：:（）()号；;，,。.、/／]{1,20}(?:校区|园区|教学点))'
)
CAMPUS_PREFIX_PATTERN = re.compile(
    rf'(?P<campus>{EXPLICIT_CAMPUS_LABEL})[：:]\s*'
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
    campus_name = normalize_text(campus_name).strip('；;，,。.、/／ ')
    return place_name if campus_name in place_name else place_name + campus_name


def split_explicit_campus_addresses(
    place_name: str, original_address: str
) -> list[tuple[str, str]]:
    """拆分带明确校区标签的单行或多行地址。"""
    raw_lines = [
        normalize_text(address_line)
        for address_line in str(original_address).splitlines()
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
                        place_name, suffix_match.group('campus')
                    ),
                    suffix_match.group('address'),
                ))
            else:
                locations.append((place_name, part))
    for line in lines:
        matches = list(CAMPUS_PREFIX_PATTERN.finditer(line))
        if matches and matches[0].start() == 0:
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                address = GRADE_NOTE_PATTERN.sub(
                    '', line[match.end():end]
                ).strip('；;，,。.、/／ ')
                if not address:
                    return [(place_name, original_address)]
                locations.append((
                    append_campus_name(place_name, match.group('campus')),
                    address,
                ))
            continue
        matches = list(CAMPUS_PAREN_PREFIX_PATTERN.finditer(line))
        if matches and matches[0].start() == 0:
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                address = normalize_text(
                    line[match.end():end].strip('；;，, ')
                )
                if not address:
                    return [(place_name, original_address)]
                locations.append((
                    append_campus_name(place_name, match.group('campus')),
                    address,
                ))
            continue
        suffix_segments = list(CAMPUS_SUFFIX_SEGMENT_PATTERN.finditer(line))
        if (
            len(suffix_segments) > 1
            and ''.join(match.group(0) for match in suffix_segments) == line
        ):
            locations.extend((
                append_campus_name(place_name, match.group('campus')),
                normalize_text(match.group('address')).strip(
                    '；;，,。.、/／ '
                ),
            ) for match in suffix_segments)
            continue
        suffix_match = CAMPUS_SUFFIX_PATTERN.fullmatch(line)
        if suffix_match is None:
            return [(place_name, original_address)]
        locations.append((
            append_campus_name(place_name, suffix_match.group('campus')),
            suffix_match.group('address'),
        ))
    return locations or [(place_name, original_address)]


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
        current_record['attributes']['school_type'] = merge_school_types(
            current_type, incoming_type
        )
    return unique_records, len(school_records) - len(unique_records)
