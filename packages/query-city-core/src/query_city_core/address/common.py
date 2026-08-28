"""地址处理链共享的文本、行政区和记录规则。"""

import re


SOURCE_NATURES = {'web_search', 'government_information'}
COMPARISON_PUNCTUATION_PATTERN = re.compile(r'[\s，,。；;：:（）()]+')
DISTRICT_PATTERN = re.compile(r'^(.{1,15}?(?:区|县|旗))')


def compact_address(value):
    """移除地址比较和去重时无意义的空白及常见标点。"""
    return COMPARISON_PUNCTUATION_PATTERN.sub('', str(value or ''))


def extract_address_components(detail):
    """从城市之后的文本中提取区县和具体位置。"""
    district_match = DISTRICT_PATTERN.match(detail)
    district = district_match.group(1) if district_match else ''
    location = detail[len(district):] if district else detail
    return district, location


def validate_address_record(address_record):
    """校验公共地址记录的固定输入字段。"""
    if not isinstance(address_record, dict):
        raise ValueError('每条地址记录必须是对象')
    if not str(address_record.get('place_name') or '').strip():
        raise ValueError('每条地址记录必须包含非空 place_name')
    if 'original_address' not in address_record:
        raise ValueError('每条地址记录必须包含 original_address 字段')
    if address_record.get('source_nature') not in SOURCE_NATURES:
        raise ValueError('source_nature 必须是 web_search 或 government_information')
    if not str(address_record.get('source_reference') or '').strip():
        raise ValueError('每条地址记录必须包含非空 source_reference')
    if not isinstance(address_record.get('attributes') or {}, dict):
        raise ValueError('attributes 必须是对象')


def build_map_result_record(address_record):
    """为地址记录补齐地图处理结果字段。"""
    return {
        **address_record,
        'map_address': '',
        'map_status': '',
        'map_reason': '',
        'map_poi_type': '',
        'map_poi_typecode': '',
        'final_address': '',
        'final_address_source': '',
        'final_address_reason': '',
    }
