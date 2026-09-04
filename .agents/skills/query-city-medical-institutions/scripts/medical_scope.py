"""医疗机构城市级去重与物理区分桶公共逻辑。"""

import re
from pathlib import Path

from query_city_core.address.city import validate_city_context
from query_city_core.address.common import address_equivalence_key
from query_city_core.io_utils import read_json_payload

from medical_common import normalize_compact_text


MAJOR_INSTITUTION_CATEGORIES = (
    '医院',
    '基层医疗卫生机构',
    '门诊部与诊所',
    '医学检验机构',
    '其他',
)

# 归类表按顺序匹配，先命中者胜；各大类词表覆盖常见官方类型子串。
_CATEGORY_TERMS = (
    ('医院', (
        '医院',
    )),
    ('基层医疗卫生机构', (
        '卫生院',
        '卫生室',
        '卫生站',
        '卫生所',
        '保健所',
        '社区卫生',
        '医务室',
    )),
    ('门诊部与诊所', (
        '门诊部',
        '诊所',
    )),
    ('医学检验机构', (
        '医学检验',
        '检验中心',
        '检验实验室',
    )),
)


def load_unit_payload(input_path):
    """读取并校验一个行政单位目录的地址处理结果。"""
    payload = read_json_payload(input_path)
    if payload.get('stage') != 'processed_address_records':
        raise ValueError(
            f'{input_path} 阶段必须是 processed_address_records'
        )
    validate_city_context(payload.get('city_context'))
    if not isinstance(payload.get('items'), list):
        raise ValueError(f'{input_path} items 必须是数组')
    return payload


def collect_administrative_unit_payloads(input_dir):
    """收集各行政单位目录中的地址处理结果。"""
    root = Path(input_dir).resolve()
    if not root.is_dir():
        raise ValueError(f'输入目录不存在：{root}')
    unit_payloads = []
    city_name = ''
    for unit_dir in sorted(root.iterdir(), key=lambda path: path.name):
        processed_path = unit_dir / 'processed_address_records.json'
        if not unit_dir.is_dir() or not processed_path.is_file():
            continue
        payload = load_unit_payload(processed_path)
        payload_city = payload['city_context']['city_name']
        if city_name and payload_city != city_name:
            raise ValueError('各行政单位处理结果的 city 不一致')
        city_name = payload_city
        unit_payloads.append((unit_dir.name, unit_dir, payload))
    if not unit_payloads:
        raise ValueError('没有找到任何 processed_address_records.json')
    return city_name, unit_payloads


def resolve_effective_administrative_unit(record, subdivision_names):
    """按最终地址、官方原文地址、来源行政区顺序解析区级归属。"""
    subdivision_names = [name for name in subdivision_names if name]
    for address_key in ('final_address', 'original_address'):
        address_text = str(record.get(address_key) or '').strip()
        if not address_text:
            continue
        for unit_name in sorted(
            subdivision_names,
            key=len,
            reverse=True,
        ):
            if unit_name in address_text:
                return unit_name
    attributes = record.get('attributes') or {}
    return str(
        (attributes.get('administrative_unit') or '').strip()
        or (attributes.get('license_administrative_unit') or '').strip()
    )


def is_abnormal_record(record):
    """判断记录是否进入异常机构表。"""
    return (
        not str(record.get('final_address') or '').strip()
        and (
            not str(record.get('original_address') or '').strip()
            or str(
                (record.get('attributes') or {}).get('abnormal_reason') or ''
            ).strip()
        )
    )


def abnormal_reason(record):
    """返回异常记录的展示原因。"""
    attributes = record.get('attributes') or {}
    return str(
        (attributes.get('abnormal_reason') or '').strip()
        or record.get('map_reason')
        or record.get('normalization_reason')
        or '官方来源未提供可用地址'
    ).strip()


def effective_main_record(record):
    """官方地址可用但地图未确认时，主表仍展示官方地址。"""
    effective = dict(record)
    final_address = str(record.get('final_address') or '').strip()
    original_address = str(record.get('original_address') or '').strip()
    if not final_address and original_address:
        effective['final_address'] = original_address
        effective['final_address_source'] = 'official'
        effective['map_match_status'] = 'skipped'
    return effective


def _record_quality_score(record):
    """城市级合并时选择地址与官方字段更完整的记录。"""
    attributes = record.get('attributes') or {}
    return (
        bool(str(record.get('final_address') or '').strip()),
        bool(
            str(attributes.get('institution_type') or '').strip()
            and str(attributes.get('institution_level') or '').strip()
        ),
        bool(str(attributes.get('institution_type') or '').strip()),
        bool(str(attributes.get('institution_level') or '').strip()),
        bool(str(attributes.get('license_no') or '').strip()),
    )


def _dedupe_keys(record, subdivision_names):
    """返回记录在物理区合并中的候选去重键。"""
    attributes = record.get('attributes') or {}
    license_no = str(attributes.get('license_no') or '').strip()
    place_name = normalize_compact_text(record.get('place_name'))
    address_key = address_equivalence_key(
        record.get('original_address')
    )
    keys = []
    if license_no and address_key:
        keys.append(('license', license_no, address_key))
    if place_name and address_key:
        unit_name = resolve_effective_administrative_unit(
            record, subdivision_names
        )
        keys.append(('place', place_name, unit_name, address_key))
    return keys


def merge_city_records(records, subdivision_names):
    """跨目录按登记号或机构名+地址合并记录并保留质量更高者。"""
    key_owner = {}
    groups = []
    extras = []
    for record in records:
        if is_abnormal_record(record):
            extras.append(record)
            continue
        keys = _dedupe_keys(record, subdivision_names)
        if not keys:
            extras.append(record)
            continue
        matched_ids = sorted({
            owner_id
            for key in keys
            for owner_id in [key_owner.get(key)]
            if owner_id is not None
        })
        if not matched_ids:
            group_id = len(groups)
            groups.append([record])
        else:
            group_id = matched_ids[0]
            groups[group_id].append(record)
            for stale_id in matched_ids[1:]:
                if not groups[stale_id]:
                    continue
                groups[group_id].extend(groups[stale_id])
                groups[stale_id] = []
                for key, owner_id in list(key_owner.items()):
                    if owner_id == stale_id:
                        key_owner[key] = group_id
        for key in keys:
            key_owner[key] = group_id
    merged_records = [
        max(group, key=_record_quality_score)
        for group in groups
        if group
    ]
    merged_records.extend(extras)
    return merged_records


def partition_main_records(records, subdivision_names):
    """把带地址记录按物理区归属到各行政单位。"""
    partitions = {name: [] for name in subdivision_names if name}
    for record in records:
        if is_abnormal_record(record):
            continue
        unit_name = resolve_effective_administrative_unit(
            record, subdivision_names
        )
        if not unit_name:
            raise ValueError(
                f'{record.get("place_name")} 无法确定行政单位'
            )
        if unit_name not in partitions:
            raise ValueError(
                f'{record.get("place_name")} 的行政单位'
                f'“{unit_name}”不在城市行政单位列表中'
            )
        partitions[unit_name].append(record)
    return partitions


def classify_institution_category(value):
    """把官方机构类型归并为通用大类，供质量闸门比较使用。"""
    text = re.sub(r'\s+', '', str(value or ''))
    if not text:
        return ''
    for category, terms in _CATEGORY_TERMS:
        if any(term in text for term in terms):
            return category
    return '其他'
