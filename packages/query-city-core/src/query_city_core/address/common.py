"""地址处理链共享的文本、行政区和记录规则。"""

import re


SOURCE_NATURES = {'web_search', 'government_information', 'map_search'}
ADDRESS_MODES = {'web_search', 'government_list', 'map_search'}
ADDRESS_MODE_BY_SOURCE_NATURE = {
    'web_search': 'web_search',
    'government_information': 'government_list',
    'map_search': 'map_search',
}
MAP_MATCH_STATUS_VALUES = {
    'consistent', 'partial', 'conflict', 'poi_match', 'not_found',
    'ambiguous', 'error', 'skipped', 'needs_review',
}
MAP_MATCH_STATUS_LABELS = {
    'consistent': '一致',
    'partial': '部分匹配',
    'conflict': '冲突',
    'poi_match': 'POI匹配',
    'not_found': '未找到',
    'ambiguous': '多个候选',
    'error': '查询错误',
    'skipped': '未查询',
    'needs_review': '部分匹配·待复核',
}
COMPARISON_PUNCTUATION_PATTERN = re.compile(r'[\s，,。；;：:（）()]+')
DISTRICT_PATTERN = re.compile(r'^(.{1,15}?(?:区|县|旗))')
PROVINCE_PREFIX_PATTERN = re.compile(
    r'^(?:[^\s省市县区旗盟]){1,12}省'
)
LEADING_CITY_PATTERN = re.compile(r'^[^省市区县]{1,12}市')
ZONE_CITY_PREFIX_PATTERN = re.compile(
    r'^[\u4e00-\u9fff]{2,6}(?=大学城|高教园区|高校园区|大学园|职教园|'
    r'教育园区|科教城)'
)
CITY_SUFFIXES = ('市', '地区', '自治州', '盟')
ADMIN_UNIT_SUFFIXES = ('街道', '苏木', '区', '县', '旗', '镇', '乡', '市')
SUB_LEVEL_SUFFIXES = ('街道', '镇', '乡', '苏木')
DISTRICT_LEVEL_SUFFIXES = frozenset(ADMIN_UNIT_SUFFIXES) - frozenset(
    SUB_LEVEL_SUFFIXES
)
PLACE_NAME_SUFFIXES = ('校区', '校园', '分院', '分行', '支行', '分部')
MISSING_ADMIN_REASON = '地址缺少下级行政区'
SUBDIVISION_SCOPE_SUBDIVISION = 'subdivision'
SUBDIVISION_SCOPE_CITY = 'city'
SUBDIVISION_SCOPES = {
    SUBDIVISION_SCOPE_SUBDIVISION,
    SUBDIVISION_SCOPE_CITY,
}
_ADMIN_UNIT_PATTERN = re.compile(
    r'^(.{1,20}?(?:' + '|'.join(
        re.escape(suffix)
        for suffix in sorted(ADMIN_UNIT_SUFFIXES, key=len, reverse=True)
    ) + r'))'
)


def compact_address(value):
    """移除地址比较和去重时无意义的空白及常见标点。"""
    return COMPARISON_PUNCTUATION_PATTERN.sub('', str(value or ''))


def extract_admin_unit_components(detail):
    """从城市之后的文本中提取下级行政区和具体位置。"""
    match = _ADMIN_UNIT_PATTERN.match(detail)
    admin_unit = match.group(1) if match else ''
    location = detail[len(admin_unit):] if admin_unit else detail
    return admin_unit, location


def address_detail_key(value):
    """提取最后道路与门牌号作为同址比较键。"""
    value = re.sub(r'\s+', '', str(value or ''))
    number_matches = list(re.finditer(r'\d+(?:[-－]\d+)?号', value))
    if not number_matches:
        return value
    number_match = number_matches[-1]
    road_positions = [
        value.rfind(suffix, 0, number_match.start())
        for suffix in ('大道', '大街', '路', '街', '巷', '弄', '道')
    ]
    road_position = max(road_positions)
    if road_position < 0:
        return value
    detail_start = 0
    for separator in ('省', '市', '区', '县', '街道', '街', '镇', '乡'):
        separator_position = value.rfind(separator, 0, road_position)
        if separator_position >= detail_start:
            detail_start = separator_position + len(separator)
    return value[detail_start:number_match.end()]


def address_equivalence_key(value):
    """取得用于同址比较的道路与门牌键，去除省份前缀。"""
    value = re.sub(r'\s+', '', str(value or ''))
    value = re.sub(r'^中国', '', value)
    value = PROVINCE_PREFIX_PATTERN.sub('', value)
    value = LEADING_CITY_PATTERN.sub('', value)
    value = ZONE_CITY_PREFIX_PATTERN.sub('', value)
    return address_detail_key(value)


def strip_city_prefix(value, city):
    """移除地址开头的目标城市前缀。"""
    value = str(value or '')
    return value[len(city):] if value.startswith(city) else value


def resolve_target_administrative_unit(address_record):
    """按下级行政区检索来源返回目标区，否则不限制行政区。"""
    attributes = address_record.get('attributes') or {}
    if attributes.get('subdivision_scope') == SUBDIVISION_SCOPE_CITY:
        return ''
    return str(attributes.get('administrative_unit') or '').strip()


def validate_address_record(address_record):
    """校验公共地址记录的固定输入字段。"""
    if not isinstance(address_record, dict):
        raise ValueError('每条地址记录必须是对象')
    if not str(address_record.get('place_name') or '').strip():
        raise ValueError('每条地址记录必须包含非空 place_name')
    if 'original_address' not in address_record:
        raise ValueError('每条地址记录必须包含 original_address 字段')
    if address_record.get('source_nature') not in SOURCE_NATURES:
        raise ValueError(
            'source_nature 必须是 web_search、government_information 或 map_search'
        )
    if (
        'address_mode' in address_record
        and address_record.get('address_mode') not in ADDRESS_MODES
    ):
        raise ValueError(
            'address_mode 必须是 web_search、government_list 或 map_search'
        )
    if not str(address_record.get('source_reference') or '').strip():
        raise ValueError('每条地址记录必须包含非空 source_reference')
    if not isinstance(address_record.get('attributes') or {}, dict):
        raise ValueError('attributes 必须是对象')


def resolve_address_mode(address_record):
    """返回记录应采用的处理模式；未显式给出时按来源证据推导。"""
    address_mode = str(address_record.get('address_mode') or '').strip()
    if address_mode:
        return address_mode
    source_nature = str(address_record.get('source_nature') or '').strip()
    return ADDRESS_MODE_BY_SOURCE_NATURE.get(source_nature, '')


def build_map_result_record(address_record):
    """为地址记录补齐地图处理结果字段。"""
    return {
        **address_record,
        'map_address': '',
        'map_match_status': '',
        'map_reason': '',
        'map_poi_type': '',
        'map_poi_typecode': '',
        'final_address': '',
        'final_address_source': '',
        'final_address_reason': '',
    }


def format_map_match_status(value):
    """将地图匹配状态转换为稳定的中文展示文本。"""
    status = str(value or '').strip()
    return MAP_MATCH_STATUS_LABELS.get(status, status or '未查询')

