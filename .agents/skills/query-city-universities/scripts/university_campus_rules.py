#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校领域统一规则：校区语义、地址清洗与来源判定。"""

import re
from urllib.parse import urlparse

from query_city_core.address.city import read_city_catalog


HOMEPAGE_PATHS = (
    '',
    '/',
    '/index.html',
    '/index.htm',
    '/index.shtml',
    '/index.php',
    '/default.aspx',
)
MULTI_CAMPUS_ENUM_MARKERS = (
    '设有',
    '分别是',
    '包括',
    '现有',
    '共有',
    '拥有',
    '下设',
    '分为',
    '分别为',
    '分布在',
    '以及',
)
ASSOCIATION_METHOD_CONFIDENCE = {
    'inline_campus_prefix': 3,
    'page_title': 3,
    'charter_clause': 2,
    'dom_context': 1,
    'unmatched': 0,
}
OFFICE_NOISE_PATTERN = re.compile(
    r'公司|集团|有限公司|大厦|写字楼|商务中心|广场|商城|'
    r'菜鸟驿站|快递|后勤处|收发室|小红楼|校友会|'
    r'招生办|就业办|函授|报名点|学习中心|星光映景|南方财经|办公|自编|'
    r'学费|收费标准|元/|生·学年|'
    r'号\s*\d+[、，,]\s*\d+|\d+(?:层|室|房)|'
    r'[A-Za-z]*\d{1,4}(?:[-－]\d{1,4})?(?:室|房|层|座)?$'
)
FEE_NOISE_PATTERN = re.compile(r'学费|收费标准|元/|生·学年|住宿费')
INSTITUTION_SUFFIX_PATTERN = re.compile(
    r'(?:大学|学院|学校|中学|小学|幼儿园)$'
)
INSTITUTION_TAIL_PATTERN = re.compile(
    r'(?P<head>.*?号)(?P<tail>'
    r'(?:省|市|自治区|区|县)?[\u4e00-\u9fff]{2,40}?'
    r'(?:大学|学院|学校|中学|小学|幼儿园))$'
)
ROOM_CODE_SUFFIX_PATTERN = re.compile(
    r'[（(]?\s*[A-Za-z]{0,3}\d{1,4}(?:[-－]\d{1,4})?'
    r'(?:室|房|层|座)?\s*[）)]?$'
)
CONTACT_LABEL_TAIL_PATTERN = re.compile(
    r'(?<![0-9A-Za-z\u4e00-\u9fff])\s*'
    r'(?:TEL|电话|传真|E-?MAIL|邮箱|邮编|QQ|微信)'
    r'(?:\s*[：:])?(?:\s*[0-9A-Za-z@.\-_]+)?\s*$',
    re.IGNORECASE,
)
ROAD_SUFFIXES = ('大道', '大街', '公路', '路', '街', '巷', '弄', '道')
NUMBER_TAIL_PATTERN = re.compile(
    r'([0-9A-Za-z一二三四五六七八九十百]+(?:[-－][0-9A-Za-z一二三四五六七八九十百]+)?'
    r'号(?:院)?)'
)
DIRECTION_DISTANCE_PATTERN = re.compile(
    r'(?:[东南西北]行|向[东南西北]|往[东南西北]|[东南西北]方向)'
    r'\s*\d+(?:\.\d+)?\s*(?:千米|公里|米)'
)
NARRATIVE_DESCRIPTION_PATTERN = re.compile(
    r'主要承担|教育任务|培训任务|承担[^，。；]{0,12}(?:教学|培训)任务|'
    r'占地面积|规划建筑面'
)
CHINESE_DIGITS = {
    '一': 1,
    '二': 2,
    '两': 2,
    '三': 3,
    '四': 4,
    '五': 5,
    '六': 6,
    '七': 7,
    '八': 8,
    '九': 9,
}

_CITY_CATALOG = read_city_catalog()


def normalize_compact_text(value):
    """删除名称或地址中的全部空白。"""
    return re.sub(r'\s+', '', str(value or ''))


def has_multi_campus_enumeration(value):
    """判断文本是否出现多校区枚举或汇总句式。"""
    text = normalize_compact_text(value)
    return any(marker in text for marker in MULTI_CAMPUS_ENUM_MARKERS)


def convert_chinese_number(value):
    """把门牌号中的中文数字转换为阿拉伯数字便于比较。"""
    text = str(value or '')
    result = []
    index = 0
    while index < len(text):
        char = text[index]
        if char not in CHINESE_DIGITS and char != '十':
            result.append(char)
            index += 1
            continue
        start = index
        while index < len(text) and (
            text[index] in CHINESE_DIGITS or text[index] == '十'
        ):
            index += 1
        sequence = text[start:index]
        if '十' in sequence:
            parts = sequence.split('十')
            tens = CHINESE_DIGITS.get(parts[0], 1) if parts[0] else 1
            ones = CHINESE_DIGITS.get(parts[1], 0) if len(parts) > 1 else 0
            result.append(str(tens * 10 + ones))
        else:
            result.append(str(sum(CHINESE_DIGITS[c] for c in sequence)))
    return ''.join(result)


def normalize_address_for_key(value):
    """生成同址比较前的统一文本：去空白并把中文数字转阿拉伯。"""
    return convert_chinese_number(normalize_compact_text(value))


def _road_suffix_segment(value):
    """取文本最后一段道路名称（不含门牌号）。"""
    text = str(value or '')
    road_positions = [
        text.rfind(suffix)
        for suffix in ROAD_SUFFIXES
    ]
    road_position = max(road_positions)
    if road_position < 0:
        return ''
    road_end = road_position + len(ROAD_SUFFIXES[
        road_positions.index(road_position)
    ])
    road_start = road_position
    while road_start > 0:
        previous = text[road_start - 1]
        if previous in '省市区县镇乡街道和与的':
            break
        if re.match(r'[\u4e00-\u9fff]', previous):
            road_start -= 1
            continue
        break
    return text[road_start:road_end]


def physical_location_key(value):
    """取地址的道路与门牌号作为同址键。"""
    text = normalize_address_for_key(value)
    number_matches = list(NUMBER_TAIL_PATTERN.finditer(text))
    if not number_matches:
        return text
    number_match = number_matches[-1]
    road = _road_suffix_segment(text[:number_match.start()])
    if not road:
        return text
    road_start = text.rfind(road, 0, number_match.start())
    return text[road_start:number_match.end()]


def road_name(value):
    """取地址中的道路名称（统一数字写法，不含门牌）。"""
    return _road_suffix_segment(normalize_address_for_key(value))


def has_house_number(value):
    """判断地址文本是否包含中文或阿拉伯数字门牌号。"""
    return bool(NUMBER_TAIL_PATTERN.search(str(value or '')))


def has_direction_distance_noise(address):
    """判断地址文本是否实际是“往某方向 X 公里”一类说明文字。"""
    return bool(DIRECTION_DISTANCE_PATTERN.search(str(address or '').strip()))


def is_narrative_description(address):
    """判断地址文本是否只是校区职责/面积叙述而非门牌地址。"""
    text = str(address or '').strip()
    if not NARRATIVE_DESCRIPTION_PATTERN.search(text):
        return False
    return not bool(
        re.search(r'(?:大道|大街|公路|路|街|巷|弄|道|\d+号)', text)
    )


def canonical_campus_name(value):
    """把父校区下的子校区/校园折叠为子校区名。"""
    campus = normalize_compact_text(value)
    if campus.endswith('校区校园'):
        campus = campus[:-2]
    hierarchical = re.fullmatch(r'(.+校区)(.+校区|.+校园)', campus)
    if hierarchical:
        return hierarchical.group(2)
    return campus


def strip_school_name_tail(address, school_name):
    """截断学校全名之后追加的房间或单位后缀。"""
    text = normalize_compact_text(address)
    school = normalize_compact_text(school_name)
    if not school or school not in text:
        return str(address or '').strip()
    school_position = text.find(school)
    head = text[:school_position].strip(' ，,；;：:|｜')
    tail = text[school_position + len(school):].strip(' ，,；;：:|｜')
    if head and tail and re.search(r'(?:号|路|街|大道|巷)$', head):
        return head
    return str(address or '').strip()


def strip_room_code_suffix(address):
    """删除地址末尾的楼栋房间码。"""
    text = str(address or '').strip()
    while True:
        stripped = ROOM_CODE_SUFFIX_PATTERN.sub('', text).strip(' ，,；;：:|｜')
        if stripped == text:
            return text
        text = stripped


def strip_contact_label_tail(address):
    """删除地址末尾以空白或标点分隔的联系词及其号码尾巴。"""
    text = str(address or '').strip()
    while True:
        stripped = CONTACT_LABEL_TAIL_PATTERN.sub(
            '', text
        ).strip(' ，,；;：:|｜')
        if stripped == text:
            return text
        text = stripped


def has_contact_label_noise(address):
    """判断地址文本是否仍以联系词结尾。"""
    return bool(CONTACT_LABEL_TAIL_PATTERN.search(str(address or '').strip()))


def clean_address_text(address, school_name=''):
    """按高校场景规则清洗地址文本。"""
    cleaned = strip_school_name_tail(address, school_name)
    cleaned = strip_institution_name_tail(cleaned)
    cleaned = strip_room_code_suffix(cleaned)
    return strip_contact_label_tail(cleaned)


def has_fee_noise(address):
    """判断地址文本是否实际是学费/住宿费等收费行。"""
    return bool(FEE_NOISE_PATTERN.search(str(address or '').strip()))


def is_institution_only_address(address):
    """判断地址文本整串只是机构名称而非门牌地址。"""
    text = normalize_compact_text(address)
    if not INSTITUTION_SUFFIX_PATTERN.search(text):
        return False
    if re.search(r'(?:大道|大街|公路|路|街|巷|弄|\d+号|\d+栋|\d+座|\d+楼)', text):
        return False
    return bool(re.search(r'[\u4e00-\u9fff]{2,8}市', text))


def is_rejected_university_address(address):
    """判断候选文本是否属于必须丢弃的噪音。"""
    return bool(
        has_fee_noise(address)
        or is_institution_only_address(address)
        or has_direction_distance_noise(address)
        or is_narrative_description(address)
    )


def strip_institution_name_tail(address):
    """截断门牌号之后追加的学校/学院等机构名称。"""
    text = str(address or '').strip()
    match = INSTITUTION_TAIL_PATTERN.search(text)
    if not match:
        return text
    return match.group('head').strip(' ，,；;：:|｜')


def is_office_noise_address(address):
    """判断清洗后的无校区地址是否仍像办公或报名点。"""
    return bool(OFFICE_NOISE_PATTERN.search(str(address or '').strip()))


def find_foreign_city_campus(value, target_city=''):
    """地点文本出现目标城市以外的城市校区词时返回城市全名。"""
    text = normalize_compact_text(value)
    target_short = ''
    if target_city:
        target_core = target_city[:-1] if target_city.endswith('市') else target_city
        target_short = target_core
    for full_name in _CITY_CATALOG:
        if full_name == target_city:
            continue
        short_name = full_name[:-1] if full_name.endswith('市') else full_name
        if len(short_name) < 2 or short_name == target_short:
            continue
        if re.search(
            r'(?:^|[^\u4e00-\u9fff])' + re.escape(short_name) + r'(?=校区|校园)',
            text,
        ):
            return full_name
    return ''


def classify_page_source(source_url, page_title=''):
    """按网址与标题归类页面来源类型。"""
    path = urlparse(str(source_url or '')).path.lower().rstrip('/')
    if path in HOMEPAGE_PATHS:
        return 'homepage'
    title = normalize_compact_text(page_title)
    if '章程' in title:
        return 'charter'
    if any(marker in title for marker in ('学校简介', '学院简介', '概况')):
        return 'overview'
    if any(marker in title for marker in ('联系我们', '联系方式')):
        return 'contact'
    if re.search(r'校区|校园', title):
        return 'campus'
    return 'other'
