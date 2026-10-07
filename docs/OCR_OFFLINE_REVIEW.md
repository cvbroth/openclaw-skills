# 离线OCR复核与质量筛查（开发实验）

本能力只读取显式提供的既有原图、OCR checkpoint及结果，不推理、不扫描NAS、不接入生产FileTools。原有空间恢复模块继续使用；没有新增Web服务、账号、视觉模型或生产依赖。安装包包含静态HTML模板，分析使用既有Pillow。浏览器不执行OCR文本或附件配置。

## 构建与使用

```bash
python scripts/build_ocr_review_bundle.py \
  --batch PRIVATE/batch-progress.json --images PRIVATE/images \
  --config deploy/ocr-screening-v1.json --metadata PRIVATE/page-metadata.json \
  --comparisons PRIVATE/prior-comparisons --pages 127 131 23 114 11 \
  --output PRIVATE/new-package --zip PRIVATE/new-package.zip \
  --public-summary PRIVATE/text-free-summary.json
```

省略 `--pages` 仅使用checkpoint明确列出的页面，不发现其他文件；可显式指定未来已授权范围，本轮只20页。metadata是页号为键的JSON对象，可含 `printed_page`、`printed_page_evidence`、`dpi`、`source_damage`。缺失印刷页码显示未知，不用物理页偏移猜测。图片SHA须匹配checkpoint，尺寸与原生OCR一致；原件不改。输出目录/ZIP/公开摘要须是新路径。

完整解压ZIP，直接打开 `index.html`。全部图片/原始JSON/Markdown/当前修订及裁片在包内，`file://` 下无需fetch、联网或服务。中文界面使用用户系统中文字体，不附带字体或认证系统。按页、风险、状态筛选，每组25项，裁片点击放大，整页入口独立打开。原图裁片坐标与修订后的定位分开显示；当前整理文字可能是整个目标块，修改/非正文会作用于整个块。

每项有稳定ID、物理页、已核实印刷页、坐标、原始/当前文字、风险来源、上下文、恢复依据和预留视觉记录。相同目标/区域/文字合并提醒，来源数组不丢。原生识别分不等于正确概率。整页筛查面板与单项状态独立。

选择确认文字、修改文字、位置/顺序、无法确定、原图无法辨认/需更清晰来源或非正文；**填写理由并加入草稿**。草稿不自动保存，可下载/恢复同版本草稿JSON。导出确认JSON后交回开发侧；浏览器不直接写服务器。演示包初始全部未确认。

```bash
python scripts/import_ocr_review.py --bundle PRIVATE/package \
  --receipt PRIVATE/ocr-confirmations.json \
  --reviewer-type human --reviewer-name '实际审阅者名称'
```

导入者须根据真实来源填写 `human` 或 `developer-agent`，与回执一致；身份是自行声明并由开发侧核对，**不是账号认证或数字签名**。Agent测试回执只能标developer-agent，不能标用户确认。

校验源图、原始OCR、原Markdown和裁片SHA、当前修订哈希、ID、操作字段、目标、坐标边界、理由及同目标冲突；拒绝重复回执、过期修订、未知ID/操作、无依据改写和版本冲突。包内 `CURRENT` 指向唯一最新修订，单写入锁防止并发。失败前不会应用半批操作；若写盘中断留下未完成新修订，停止并人工核对恢复，不删除历史或自动越过它。不要把旧包当成最新账本接收后续回执。

每次导入创建 `revisions/revision-N.json`、独立Markdown和 `review-N.html`，旧HTML、原始资产和所有修订保留。记录前后值、真实审阅者类型/名称、范围、理由、回执来源、导入UTC时间、父修订哈希；原图/OCR哈希沿用同一链。重新分发最新HTML时仍需带整个目录。

文字确认不能解决待定位、次序或重复问题；待定位片段改字后仍待定位，只有明确位置操作才能插入对应正文位置，不追加到末尾。位置操作须指定同页真实 `before_target` 和原图像素框。无可靠目标且不是pending片段时，拒绝创建新正文块以免重复。非正文排除只作用于派生正文，原件及审计仍保留。疑点单项解决不等于整页通过。整页确认须显式human全页操作，且无未解决结构阻塞/无法确定/源图不可辨认；后续任何单项改动使旧整页确认失效。

## 版本化筛查配置

默认 `deploy/ocr-screening-v1.json`，示例 `deploy/ocr-screening.example.json`。JSON只作为开发筛查数据，不执行脚本，不作为附件生产配置。读取时拒绝未知组/键、布尔伪数值、NaN、越界、无效组合。记录原配置字节SHA和version；它们包含在修订哈希内。更改参数建立新分析包，**不覆盖旧问题和确认，不把新包自动声明为替代旧确认账本**；历史告警保留在旧包。没有配置迁移/确认继承功能。

| 组/参数 | 默认 | 合法范围、用途 |
|---|---:|---|
| image.analysis_width | 600 | 整数200–1600；固定分析尺度，不能跨尺度直接比较模糊指标 |
| image.blur_edge_variance_min | 100 | 0–65025；灰度边缘方差低于阈值提醒，不是可读性判定 |
| image.contrast_p95_p5_min | 80 | 0–255；全局95/5百分位灰度差，局部缺笔可漏报 |
| image.skew_degrees_max | 1 | 0–3；粗倾斜候选阈值 |
| image.skew_search_degrees | 3 | 整数1–3；±角度整度搜索，非精确纠偏 |
| image.skew_gain_min | 0.02 | 0–10；水平墨迹投影改善不足则角度未知，不能当0度 |
| image.minimum_dpi | 200 | 50–1200；显式输入DPI，未声明则未知；不代表有效字形分辨率 |
| image.edge_band_fraction | 0.01 | .001–.1；边缘墨迹带宽 |
| image.edge_ink_fraction_max | .08 | 0–1；边缘暗像素比例候选，不证明真的裁掉文字 |
| ocr_structure | 原实验规则 | 复用spatial_overlap/lane_overlap/same_row_overlap (0,1]、box_padding_px≥0、low_recognition_score (0,1]；当前低分<.90 |
| risk.low_score_fraction_medium/high | .03/.15 | 0–1且medium≤high；按非空识别行计算比例，达到阈值触发 |
| mandatory_review | 见JSON | pending/order/duplicate/critical_disagreement/source_damage不能关闭；recovered/question_option用于筛查触发，原结构提醒与复核阻塞仍保留 |
| future_visual.trigger_risks | 见JSON | 明确枚举的风险名；只形成候选，不调用模型 |
| future_visual.normal_page_sample_fraction | .05 | 0–1；无触发页按图像SHA+配置version确定性抽样，不是已抽查结论 |
| scoring | disabled/null/null | 本版不提供总分，不接受未经实现的权重或归一化 |

图像、识别、结构分别输出low/medium/high/unknown、指标、原因和检测范围，不合成综合准确率。强制复核不被高OCR分抵消。图像全局指标不涵盖所有局部损伤；多栏/侧栏会干扰倾斜投影。没有同页副本时识别分歧覆盖为未知，没有原生结果时结构/识别为未知。没有告警或候选触发不等于已核实正确。

初始阈值**未统计校准**。合成边界测试验证方向/边界/缺失行为，当前参考验证高分也会错数字；不能据此宣称一般化的误报率或漏报率。生产接入还需受限入口、资源/可移植性、安全/身份及用户验收设计，不能把开发脚本冒充正式发布。

## 可复算验证

标准库unittest（需既有Pillow）：

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_ocr_review_bundle.py
PYTHONPATH=src python -m unittest discover -s tests -p test_ocr_spatial_review.py
```

可选开发UI检查 `scripts/browser_smoke_ocr_review.py --bundle PRIVATE/package --output NEW_PRIVATE_DIRECTORY` 使用Playwright1.55.0/Chromium140.0.7339.16（只开发依赖）。浏览器上下文offline，验证本地筛选/裁片和下载JSON，不导入演示包或冒充人类验收。官方安装/API说明：[Playwright Library](https://playwright.dev/python/docs/library)。本机Ubuntu26.04不在该版本支持映射内，开发测试用Ubuntu24.04 fallback构建，共享库仅解包到/tmp；这不是对所有客户端的兼容保证。可选 `--font` 仅在开发截图注入本地字体，不复制到包。

已确认源图受损的整页提醒不能用空文字确认或非正文操作解除；本版只能保留未知/源图不可辨认。获得更清晰来源后需要明确建立新的来源/修订流程，尚未实现自动替换源图或迁移确认。
