# query_city_core 公共核心层

## 本层职责

查询城市类 Skill 共享的公共运行能力：城市标准化、官网页面抓取、
地址规范化与地图验证、Excel 输出格式、网络直连兜底与配置读取；
本层不依赖任何 Skill 的业务规则。

## 目录结构

- `address/`：地址处理子包，功能与修改记录见 `address/README.md`。
- `assets/`：固定资产，`china_city_catalog.json` 为城市目录。
- `official/`：官方数据框架（来源读取、栏目/附件收集、通用提取引擎），
  功能与修改记录见 `official/README.md`。
- `web/`：通用网页采集能力（官网页面抓取、域名现用性探测、浏览器/直连
  兜底、访问审计）。

## 文件功能

| 文件 | 功能 |
| --- | --- |
| `__init__.py` | 包标记与版本号。 |
| `access.py` | HTTP 直连兜底：urllib/curl 依次尝试、访问审计、浏览器指纹常量（`USER_AGENT`、`BROWSER_HEADERS`）。 |
| `env_utils.py` | 从进程环境或工作区 `.env` 读取配置。 |
| `excel_style.py` | 查询结果工作簿统一格式、地址输出列、来源超链接与工作表校验。 |
| `host_gate.py` | 进程内按主机节流的调度门：同主机并发上限与最小请求间隔，供批量抓取/下载共用。 |
| `io_utils.py` | 公共 JSON 文件读写（`read_json_payload`/`write_json_payload`）。 |
| `official/` | 官方来源读取器、栏目链接/来源文件/详情页收集器与通用提取引擎，详见 `official/README.md`。 |
| `web/` | 通用网页采集：`OfficialPageFetcher`、页面抓取、域名现用性探测与直连/浏览器兜底。 |

## 修改记录

### 2026-09-03

- `city.py`、`amap_client.py` 移入 `address/`，命令入口同步为
  `python -m query_city_core.address.city`，不再保留根目录同名模块。

### 2026-09-02

- 新增 `web/probe_domains.py`
  - 通用官网域名探测：逐条访问 `home_url`，输出可达性、跳转终域、
    白名单归属与页面身份匹配；记录字段使用中立的 `place_id`/
    `place_name`，不感知学校/医院/政府机关语义。
- 新增 `official/` 子包：原 `source_readers/` 迁入 `official/readers`，
  原 `directory_links.py`、`linked_pages.py`、`source_files.py` 迁入
  `official/collectors`；基础教育“检查/提取计划”中的通用规则推理迁入
  `official/extract`，场景词表由 Skill 注入，旧根模块与 Skill 副本删除。
- 新增 `web/` 子包：原 `fetch_official_page.py` 迁入 `web/`，调用方
  与测试改为新包路径。
- `address/verify.py`
  - 记录新增顶层 `address_mode`（`web_search`/`government_list`/`map_search`），
    `source_nature` 降级为来源证据；结构化有效地址直接采用、不再调用高德，
    两个来源模式按宽松/严格两级 POI 兜底，`map_search` 本轮为占位；
    POI 名称比较保留行政区前缀与状态词容差及地图地址引导文本清洗，
    详见 `address/README.md`。
- 新增 `host_gate.py`
  - `HostRequestGate` 按主机限制并发并保持最小请求间隔，默认同主机
    串行（间隔 0.3 秒）；`extract_url_host()` 解析请求主机。
- `source_files.py`、`directory_links.py`、`linked_pages.py`
  - 批量抓取/下载入口支持 `max_workers`、`host_max_workers`、
    `host_min_interval` 参数，取消硬编码 `max_workers=8`；
    同批次内同域名请求自动节流，不同主机仍可并行。
- 新增 `linked_pages.py`
  - 基础教育 Skill 的 `collect-details` 实现（名录页 → 同构详情页批量
    保存）下沉到公共层，Skill 只保留命令入口；
  - 允许域名只接受相同主机的页面，与原 Skill 行为保持一致。
- `source_files.py`
  - 下载清单支持可选 `allowed_domain`：给出时按最终地址域名（含子域）
    校验，跳转到允许域名之外的下载按失败记录且不写文件。
- 新增 `directory_links.py`、`source_files.py`
  - 栏目页候选链接收集与来源文件批量下载拆到公共层，供政府、医院、
    学校等不同来源检索场景共用，不包含任何 Skill 业务规则；
  - 清单 stage 使用中立命名：`directory_link_manifest`/`directory_links`、
    `source_download_manifest`。
- `access.py`、`fetch_official_page.py`
  - `normalize_domain()`、`is_url_in_domains()` 下沉到 `access.py`
    （纯 URL 域名逻辑、无浏览器依赖），`fetch_official_page.py`
    改为从 `access.py` 导入，调用方保持兼容。
- `access.py`
  - 新增 `_record_attempt()`，合并 6 处重复的访问审计字典。
  - 返回内容增加 HTTP 响应头声明的字符集；
    curl 通过 `%{content_type}` 回传 Content-Type 供解码使用。
- `fetch_official_page.py`
  - `USER_AGENT` 收敛到 `access.py` 单一来源，删除重复定义；
  - `OfficialPageFetcher` 新增公开的 `new_context()`，`fetch`/`fetch_pages`
    复用同一浏览器上下文创建逻辑，并可供外部按学校管理 context 生命周期。
  - `decode_html_content` 支持 HTTP 头字符集，按 BOM → HTTP 头 → meta → UTF-8 解码。
- `amap_client.py`
  - 重试等待改为指数退避（1 秒起、4 秒封顶，含抖动）；
  - 新增 `as_list()`，统一三个查询函数的列表兜底。
- `excel_style.py`
  - 新增 `DATE_CELL_PATTERN` 与 `format_date_cell()`，
    供各 Skill 统一日期单元格的格式化与校验；
    地址、地址获取方式、地图匹配状态、信息来源四列本就由
    `extend_address_output_columns`/`build_address_output_values` 提供，
    两个 Skill 均已复用公共层；
  - 新增 `write_workbook_atomically()`，原子保存工作簿并在替换前复核，
    高校与基础教育两个 Skill 共用，删除 Skill 侧重复实现。
- `__init__.py`
  - docstring 改为中文。
- `address/process.py`
  - 地址处理改为「逐条规范化后立即调用地图解析」，
    不再先统一规范化再统一查询高德，避免地图请求堆积。
- `address/`
  - 子包内的全部改动见 `address/README.md`。
- `io_utils.py`
  - 新增公共 JSON 读写；高校 Skill 的 `script_io.py` 已删除，
    各脚本改为从公共层导入；
  - `normalize.py` 中原先不归属的 `write_json_payload` 移除。
