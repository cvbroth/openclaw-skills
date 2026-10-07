# 开发实验：空间覆盖、复核与预处理

这些入口只用于独立开发的PP-StructureV3原生结果。未接入 `filetools_extract`、生产Worker、Gateway或QQ交付；不能使用这些脚本声称已经通过生产受限调用。沿用既有OCR环境，不向生产安装依赖。

## 结果复核入口

`scripts/review_ocr_layout.py --native result.json --markdown result.md --physical-page N --output NEW_DIRECTORY [--rules deploy/ocr-review-experiment.json] [--image source.png]`

输出目录必须不存在，原始结果只读。输出 `review.json`、`repaired.md`，可选 `overlay.png`。后者需要固定开发镜像已有Pillow；调用子进程使用运行环境的 `sys.executable`，不能假设命令名 `python` 指向相同虚拟环境。原始图像尺寸必须匹配原生坐标。

库 `nas_filetools.ocr_review` 无Paddle/大模型运行依赖，不重新识别。输入原生结果必须有成对的 `overall_ocr_res.rec_texts/rec_boxes/rec_scores` 及 `parsing_res_list.block_content/block_bbox/block_label`。无坐标或数组不齐则拒绝，不伪造空间信息。坐标单位是原输入图片像素，不是PDF点或屏幕缩略图像素。

`DEFAULT_RULES` 与JSON配置使用相同实验值：

| 键 | 初始值 | 用途与限制 |
|---|---:|---|
| spatial_overlap | 0.35 | 局部块匹配最低空间相交比例，相交面积/较小框面积 |
| box_padding_px | 8 | 匹配及锚点容差，针对当前220dpi实验；不是任意DPI通用值 |
| lane_overlap | 0.45 | 恢复锚点必须在同一水平区域 |
| same_row_overlap | 0.45 | 同行两列按横坐标排序，不将整页强行改成行优先 |
| low_recognition_score | 0.90 | 低分提醒，高分仍需结构和关键文字复核 |

阈值未经统计校准，不用作综合准确率。比较文本时合并空白和标点差异，但不将①变成1、否定词变成同义词，也不改输出文字。相同文本只能消耗一次局部字符容量；跨块拆合须空间相交。存在模糊块内重复或空间冲突时保留解释，不假定位置确定。

只在明确正文锚点间恢复raw识别行。原解析块不改、不重排；恢复的坐标、原始行索引、插入位置和上下锚点写入记录。无法确定的片段独立保留；不是把raw全文按行重拼成新的正文。原生次序有问题时仅标候选，不静默修正。多列、材料题或页边碎字可能不能安全定位。

## 记录与复核状态

- `recognition`：原生逐行识别分和来源；不提供正确概率。
- `structure`：空间覆盖、恢复、待定位、重复、阅读顺序、题号及选项候选；候选不是已核实题数。
- `coverage_before/after`、`recovered`、`pending_fragments`：页码、区域、原文和匹配/恢复依据。
- `critical_regions`、`low_score_regions`：重点字符及实验分数提醒。
- `review_records`：后续视觉或人工确认记录容器。审阅者类型应明确为human/developer-agent/其他真实来源，保留范围、状态和证据，不伪造人工认证。
- `review_status`：未定位片段为“无法确定”；未有人工确认或有结构阻塞为“需复核”；仅明确人类整页确认且无结构阻塞时可“通过”。没有用户确认的开发Agent看图记录不能触发human通过。

后处理成功、无告警或高OCR分都不能替代逐页/逐块内容验收。原生结果和历史修订只增量保留。

## 有限预处理

`scripts/prepare_ocr_preprocessing.py --images READONLY_IMAGES --output NEW_DIRECTORY --pages EXPLICIT_PAGES`

仅生成灰度+对比度1.25，以及灰度+3×3中值+对比度1.25两种副本。尺寸/坐标不变，显式记录单位矩阵、参数和源/副本哈希；没有旋转或无界参数搜索。若将来增加裁切/纠偏，必须同时记录可逆坐标变换，并用合成测试验证四角映射；不能沿用单位矩阵。

用已有 `scripts/run_ocr_cpu_trial.sh` 为每个副本单页启动固定镜像。资源保持2CPU/16GiB、memory-swap总额16GiB、network none、只读模型/输入、无GPU；加载180秒/每页300秒。准备阶段和推理阶段分开，当前实验不新增下载。推理前逐次检查主机实际可用资源。原图OCR结果复用，不为对比整批重跑。

## 回归与CER

`scripts/evaluate_ocr_review.py` 参数：`--batch` 指定既有逐页checkpoint，`--reference` 指定私有看图参考，`--images` 指定对应原图，`--output` 新私有目录，`--public-summary` 新脱敏JSON；可选 `--preprocessing-manifest` 和 `--inference` 指向本次副本证据。

脚本不触发推理、不扫描NAS。核对20页图像哈希、原始内容/次序、覆盖不退化、重复和恢复次序；保留原生顺序告警。CER按人工选定完整题块ROI内raw行中心取样、题块内几何行序拼接，只删空白。原图和所有副本使用相同参考、ROI、模糊字排除规则；修改参考须看原图留记录并统一重算。CER只是所选参考的识别指标，不能替代组装完整性或整页准确率。

位置比较将一对一/拆行/合行分组，记录字符和关键标记分歧、未匹配行及识别分变化，不自动选择赢家。原图及副本全文和日志只放忽略目录；公开摘要只含页号、区域、数量、分数、配置、资源和SHA，不含参考/假设正文。

测试：`PYTHONPATH=src python -m unittest discover -s tests -p test_ocr_spatial_review.py`，或在固定隔离环境运行相关pytest。新增用例为合成文本，不能把业务题册复制进测试夹具。
