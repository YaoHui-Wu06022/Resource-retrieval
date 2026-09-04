# scripts 处理脚本

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `medical_government_flow.py` | 政府资料流程 CLI：`list-links` / `download` / `collect-details` / `platform-query` / `inspect` / `extract`；词表、来源清单适配、JSON/JSONP 来源检查、平台分页抓取、引擎调用与跨来源去重。 |
| `medical_common.py` | 医疗记录构造、执业地址拆分、外市剔除与跨来源去重。 |
| `medical_scope.py` | 城市级跨目录去重、按最终物理地址分桶、机构类型归并为通用大类（医院/基层医疗卫生机构/门诊部与诊所/医学检验机构/其他）。 |
| `build_excel.py` | 汇总各行政单位 processed 结果，跨目录去重后按物理地址分桶生成区级工作簿与城市总表；区级工作簿含「机构信息」「异常机构」，总表为“机构信息”汇总 + 各区工作表且不含异常机构表。 |
| `medical_quality_check.py` | 交付质量闸门：平台数量下界、大类覆盖与来源完整检查，写出 `quality_report.json`，未通过时退出码非 0。 |

## 命令

| 命令 | 用途 |
| --- | --- |
| `medical_government_flow.py platform-query --manifest <government_source.json>` | 按清单顶层行政单位抓取 `query_platform` 来源分页，保存原始 JSONP 页与汇总记录并回写清单。 |
| `medical_quality_check.py --input-dir <运行目录> [--output <quality_report.json>]` | 生成并校验质量报告。 |

## 修改记录

### 2026-09-03

- 删除旧 `medical_source_parsers.py` 与 `build_medical_address_records.py`，
  统一走 `medical_government_flow.py` 的 inspect/extract 公共链路；
  废除 `anomaly_records.json`，异常行改由 `build_excel.py` 推导；
  `extract` 重新接入 `deduplicate_records`，修复多地址段
  `source_reference` 累积问题。
- 医疗流程改为按直接下级行政单位默认分区检索：每区目录一份
  `government_source.json`（顶层 `city_context` + `administrative_unit`）；
  地址记录 attributes 使用 `subdivision_scope=subdivision` 与
  `license_administrative_unit`，多址拆分的无区名段以目标区补区；
  `build_excel.py` 改为 `--input-dir` 汇总各行政单位 processed 结果，
  生成每区工作簿与城市总表。
- 城市总表改为与基础教育一致的结构：先输出“机构信息”汇总表，再按行政
  单位各出一张工作表；异常机构表只保留在每区工作簿，总表不再写入
  异常机构表。
- 工作簿输出规则：机构级别为“未定级/无定级/无级别”的单元格显示为空，
  原始 processed 记录中的官方原文保持不变。

### 2026-09-04

- 新增 `query_platform` 来源形态与 `platform-query` 子命令：按行政单位
  过滤政府注册查询平台分页（JSONP），逐页校验 count 恒定并收齐后保存
  原始页证据与汇总 JSON，回写 `platform_result` 审计。
- `inspect` 支持 JSON/JSONP 汇总文件（自定义来源检查回调，未改公共核心）；
  `query_platform` 汇总记录映射 `yymc/yydz/szq/yytype/jb`，不把 `yyid`
  当登记号。
- 新增 `medical_scope.py`：城市级跨目录去重、物理地址分桶与机构类型
  大类归并；`build_excel.py` 改为先去重再按最终物理地址分桶，跨区
  多执业地址段进入对应区工作簿，不再因“记录区与目录一致”被移出。
- 新增 `medical_quality_check.py` 硬性质量闸门：数量低于平台当区总数
  × 90%、平台大类缺失且无 `no_official_source` 理由、或无任何 ready
  全量来源时阻断交付并写 `quality_report.json`。
- 机构大类归并改为有序规则表驱动，只保留医院/基层医疗卫生机构/
  门诊部与诊所/医学检验机构/其他五个兜底大类；
  `村卫生室/卫生站/卫生所/保健所`统一归入基层医疗卫生机构。
