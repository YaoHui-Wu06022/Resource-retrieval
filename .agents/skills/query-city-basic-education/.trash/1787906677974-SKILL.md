---
name: query-city-basic-education
description: "按中国城市的直接下级行政单位检索政府公开的非高校学校名录，提取学校与地址并生成区级和城市汇总 Excel。"
---

## 输入与运行条件

输入一个中国城市名称，输出该城市直接下级行政单位中的非高校学校信息。

- 若用户尚未确认 Python 环境或解释器，先询问；已经确认则不要重复询问。
- 全程使用同一环境，要求安装 `beautifulsoup4`、`lxml`、`pandas`、`openpyxl`、`xlrd` 和 `PyMuPDF`；读取 Word 还需要 LibreOffice。
- 共享运行库必须已安装且版本与 `requirements.txt` 一致；本地开发时从 `packages/query-city-core` 以 editable 模式安装，分发时安装固定版本的 wheel 或 Git tag。
- 城市查询和地址处理从进程环境或工作区 `.env` 读取 `AMAP_KEY`。
- 缺少依赖、地图密钥或公共组件时停止并说明缺项，不自行安装，也不另写临时脚本复制固定逻辑。

全部输出固定写入：

`<项目根目录>/output/<标准城市名>/<YYYY-MM-DD>/Basic_Education/`

## 执行边界与 Agent 分工

固定处理必须调用现有脚本：

| 用途 | 调用 |
| --- | --- |
| 标准化城市并取得下级行政单位 | `python -m query_city_core.city` |
| 检查来源并生成提取计划 | `scripts/build_school_records.py inspect` |
| 按已复核计划提取学校 | `scripts/build_school_records.py extract` |
| 规范化地址与地图兜底 | `python -m query_city_core.address.process` |
| 生成区级和城市工作簿 | `scripts/build_excel.py` |

来源检索、质量判断、覆盖判断和提取计划复核由 Agent 完成；学校类型规范、记录去重、地址路由、排序和工作簿格式由脚本完成。

运行环境支持子 Agent 时，主 Agent 按行政单位划分互不重叠的任务：

- 每个行政单位交给一个子 Agent；并发名额不足时分批派发，不得遗漏或重复处理。
- 子 Agent 不再向下委派，只能写入自己的行政单位目录。
- 子 Agent 负责来源检索、下载、`sources.json`、提取计划复核、学校提取和地址处理。
- 主 Agent 负责城市标准化、任务分发、逐区结果验收和最终工作簿，不让子 Agent 写城市总表。

## 1. 取得行政单位

运行：

```text
python -m query_city_core.city --city <用户城市>
```

从输出读取标准城市名和 `subdivisions`。主 Agent 按每个 `subdivisions[].name` 创建同名目录，并把完整行政单位对象、标准城市名、执行日期和该目录分配给对应子 Agent。不得增删、合并、改名或继续查询更低一级行政单位。

## 2. 检索并保存政府来源

每个子 Agent 使用自身 Web Search，先查本区教育行政部门，再查本区政府门户、上级教育部门和政府数据平台。只采用政府或教育行政部门发布且正文、附件或分页实际包含学校名录的来源；通知只有在正文或附件包含名录时才采用。

必须分别检索幼儿园、小学、初中和高中。政府来源还列出一贯制学校、完全中学、特殊教育、中等职业教育、职业高级中学、技工院校、专门学校或其他非高校类型时，一并纳入，不按固定类型排除。

先检索当年和上一年；没有合格来源或仍有覆盖缺口时，才扩大到再前一年。候选按官方性、时效性和信息量选择，不因格式不同改变优先级。不得使用地图、百科、媒体、自媒体、择校网站或第三方学校数据库作为名录来源。

入选后立即把原始 HTML、Excel、Word、PDF 或图片保存到行政单位目录。分页 HTML 保存全部名录页；附件保留原文件名和格式，不下载没有学校清单的通知附件。

写入 `sources.json` 前读取 [行政单位来源结果格式](references/source-manifest-format.md)。每个行政单位必须记录幼儿园、小学、初中和高中的覆盖状态；未找到资料也要写明状态，不得静默结束。

## 3. 检查并复核提取计划

运行：

```text
scripts/build_school_records.py inspect \
  --input <行政单位目录>/sources.json \
  --output <行政单位目录>/extraction_plan.json
```

子 Agent 检查脚本识别出的文件、页码、工作表、表格、学校列、地址列、学校类型、办学性质、固定值、向下填充列和排除行。正确规则设为 `approved = true`，来源设为 `review_status = ready`；不得手工抄写最终学校记录。

扫描 PDF 或图片被标记为 `needs_vision` 时，按来源格式参考中的视觉分支处理。有视觉能力时生成视觉结果并重新运行检查；没有视觉能力时将该来源按 `no_vision_capability` 跳过，不运行本地 OCR。

## 4. 提取学校记录

运行：

```text
scripts/build_school_records.py extract \
  --plan <行政单位目录>/extraction_plan.json \
  --output <行政单位目录>/address_records.json
```

只有 `stage = address_records` 且 `metrics.error_count = 0` 才能继续。输出记录必须包含学校名称、原始地址、学校类型、办学性质、发布日期、行政单位和可定位的信息来源；`source_nature` 固定为 `government_information`。来源没有地址时保留空值，不得推断或编造。

## 5. 处理地址

运行：

```text
python -m query_city_core.address.process \
  --input <行政单位目录>/address_records.json \
  --output <行政单位目录>/processed_address_records.json
```

确认输出 `stage = processed_address_records`。政府资料中的完整地址直接使用；缺少地址或地址不完整时由公共组件在当前行政单位内尝试地图兜底。目标城市冲突或没有合格结果时，最终地址保持为空。

子 Agent 完成后向主 Agent 返回：行政单位名称、总体状态、各类型覆盖状态、来源数、提取记录数、最终地址非空数和行政单位目录。

## 6. 生成最终工作簿

主 Agent 确认所有行政单位均已返回结果后运行：

```text
scripts/build_excel.py \
  --input-dir <Basic_Education输出目录> \
  --output <Basic_Education输出目录>/基础教育学校查询_<标准城市名>_<YYYY-MM-DD>.xlsx
```

脚本在各行政单位目录生成一份区级工作簿，并生成包含“学校信息”总表和各行政单位分表的城市工作簿。只输出最终地址非空的记录；去重、学校类型顺序、区内排序、总表按区拼接和展示格式均以脚本结果为准，不由 Agent 手工调整。

最终列固定为：序号、行政单位、学校名称、学校类型、办学性质、最终地址、地址获取方式、发布日期、信息来源。

## 完成检查

- `subdivisions` 中每个行政单位都有子 Agent 返回结果或明确的无来源状态，无遗漏和重复目录。
- 幼儿园、小学、初中和高中均完成独立检索，覆盖缺口已写入 `sources.json`。
- 每个进入汇总的行政单位都有合法的 `address_records.json` 和 `processed_address_records.json`。
- 城市总表行数等于各行政单位分表行数之和，所有输出行的最终地址非空。
- 最终工作簿可以打开，工作表和九列字段符合脚本约定。

最终回复只说明标准城市名、行政单位总数及各状态数量、来源总数、最终地址行数和最终文件绝对路径，不展开逐区检索过程。
