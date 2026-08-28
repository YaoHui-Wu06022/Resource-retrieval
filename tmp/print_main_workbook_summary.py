import json


with open("tmp/main_workbooks.json", encoding="utf-8") as stream:
    summary = json.load(stream)

for side in ("left", "right"):
    workbook = summary[side]
    print(f"{side}: {workbook['path']}")
    print(f"  sheet={workbook['sheet']}; rows={workbook['row_count']}; columns={workbook['column_count']}")
    print(f"  header={workbook['header']}")

for field in (
    "shared_record_count",
    "left_only_count",
    "right_only_count",
    "changed_shared_record_count",
    "left_duplicate_key_count",
    "right_duplicate_key_count",
    "left_type_counts",
    "right_type_counts",
):
    print(f"{field}: {summary[field]}")

for field in (
    "left_only_samples",
    "right_only_samples",
    "changed_record_samples",
):
    print(f"{field}:")
    for item in summary[field]:
        print(item)
