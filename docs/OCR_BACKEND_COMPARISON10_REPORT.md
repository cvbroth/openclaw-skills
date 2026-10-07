# OCR 后端十页横向对比（2026-10-08，隔离开发实验）

本机本轮能完成整页的是 **MinerU 4.0.10 Basic / ONNX CPU**：10/10 页；存在可见错字、题号错误和默认 Markdown 过滤页边内容，不能作为正文已正确的证明。PaddleOCR-VL 与 MonkeyOCRv2 均加载成功，但第一个整页超过 300 秒，没有完成可比较的整页输出，未扩跑其余九页，不能据此判断识别质量差。M3 只复用历史七页成功、136 页失败和两页缺失，没有新增云端调用。

保留当前测评分支 760105fdef89f561c7b396821a9fbf54f68c4901 及外层整册开发工作区。没有生产安装、配置/挂载/Skill/限额更改、服务重启、全册 OCR、正式题册生成、saved 保存或知识库导入。已有文档模板保持。没有新增路由、RAG、审核状态或评分系统。

## 1. 输入与取样

指定原件：`/srv/storage/users/chen/FileTools-Incoming/27版肖1000试题分册.pdf`，169 物理页，只读核对 SHA-256：

`0007677dc510b01ffed36bd1250fafd8a7b0101f383e3603257b45e379a6f28b`

明确目的取样，无随机种子；优先选历史 M3 原图样本，加相邻跨页 9/10 页。下列印刷页码由开发侧查看原图页脚核对，不按物理页偏移推算。全部使用同一 PDF、220dpi、RGB PNG、1819×2573；8 张复用历史原 PNG 的相同字节，9/10 仅重新渲染选定页。图片 SHA、字节数、来源在私有 `manifest.json`，没有重新 OCR 整册。

| 物理页 | 印刷页 | 选择依据 | MinerU 秒 | 进程累计峰值 RSS KiB | M3 历史 |
|---:|---:|---|---:|---:|---|
|9|4|与10相邻，第27题跨页、长题和侧栏|8.033|1308448|缺失|
|10|5|第27题延续、旧OCR第32题漏行|4.610|1444108|缺失|
|12|7|清晰单选、章节切换、横排两列选项|9.672|1308836|成功|
|16|11|长题、密集选项、标题、侧栏|5.500|1448464|成功|
|23|18|固定困难扫描、密集横排选项|4.385|1458204|成功|
|75|75|多选、章节切换、横纵排选项|4.442|1495072|成功|
|81|81|多选结尾、材料分析、长材料和小问|4.416|1529800|成功|
|136|140|固定页、多选长题、历史M3失败|5.394|1531484|两次失败|
|150|157|学科/题型/章标题及题号重置|4.190|1531760|成功|
|168|175|密集多选、小字号、长题和侧栏|4.646|1531848|成功|

12 是单独首张试跑，9 是另一个进程的首张；其时间均含惰性初始化和导出，其他为同进程后续页，不能平均后称纯模型推理时间。16 页末题延伸至未选页面，只交付页内现存内容；本轮相邻跨页测试为9/10。选页时查看过候选80及已有缩略图，但80未入十页实验、未推理、未入交付。所选十页未发现可作为实际表格、公式或插图测试的内容；这些能力未验证。

## 2. 官方路线、固定环境与模型

检查日期2026-10-08。官方下载模型属于准备，不等于云端推理；处理容器全部断网。完整实际解析依赖在 `deploy/ocr-comparison-locks/`，镜像身份及运行测量在[脱敏证据](evidence/ocr-backend-comparison10.json)。镜像构建文件保留实验用途，不是生产接入。

| 候选 | 实际版本/模型/引擎 | 结果与边界 |
|---|---|---|
|PaddleOCR-VL|PaddleOCR3.7.0 / PaddleX3.7.2 / PaddlePaddle CPU3.2.2 / NumPy2.3.5；已有VL-1.5 + PP-DocLayoutV3；native Paddle CPU|本轮升级到官方当前稳定包，继续固定已有1.5权重；不是VL1.6测试，不涵盖其他CPU引擎|
|MinerU|4.0.10，Basic，`parse_mode=ocr,image_analysis=True`，ONNX Runtime1.30.0，NumPy2.5.3|实际加载PP-DocLayoutV2、PP-OCRv6 tiny检测+small识别，及Magika standard_v3_3；**没有VLM**，不是Standard/Advanced档|
|MonkeyOCRv2|官方源码6cc0c0bb4864f2541fa6bc3a8f976cffaac8f359，zenosai/MonkeyOCRv2-B-Parsing；Python3.11.14/Torch2.5.1+cpu/Transformers4.57.1/Accelerate1.11.0，float32/eager|使用官方Linux CPU两阶段管线及预处理器，max_pixels=1003520，页面串行，未改装其他等价性不明的管线|
|M3历史|MiniMax-M3，Anthropic Messages接口，原PNG base64，非view_image|2026-10-07历史请求；输入像素/字节均一致，服务内部缩放未知。本轮新请求0|

[PaddleOCR3.7.0发布](https://github.com/PaddlePaddle/PaddleOCR/releases/tag/v3.7.0)、[VL使用说明](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md)、[MinerU4.0.10发布](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.10-released)、[MinerU档位与引擎](https://opendatalab.github.io/MinerU/usage/tiers/)、[官方模型来源](https://opendatalab.github.io/MinerU/usage/model_source/)、[Monkey官方CPU说明](https://github.com/Yuliang-Liu/MonkeyOCRv2/blob/6cc0c0bb4864f2541fa6bc3a8f976cffaac8f359/docs/cpu_support.md)。CPU支持是部署路线声明，不能据此承诺本机限时吞吐；远程客户端不需要GPU也不等于远端模型不用GPU。

模型固定来源：

- Paddle VL1.5 revision `2a4195faa5e7914c12f2fc601d72c81caf8d2da5`，主权重1,917,255,968字节，SHA `d557c9d8997ae57ed3b1b33bdf347be878cc335687f32ca105341c16973f8958`；DocLayoutV3 revision `241f8bdfc77a7c7bee915a5057aaee58c235a8d3`，130,806,572字节。
- MinerU `opendatalab/MinerU-4_models_onnx` revision `358310b4f64b95f9fefc372ad899356e4111f376`，完整仓约858MB。包含但十页未加载的公式、表格、印章权重不计作已验证能力。
- Monkey `zenosai/MonkeyOCRv2-B-Parsing` revision `e8871a0057c98378219b369f924a25ba10f392bf`，约2.065GB；主权重1,755,925,032字节，SHA `0267fdc991c9be02cf1b60405f77fe0629d084970ad9d6d08163feda3d470284`，另外两个预处理权重约4.8MB和288.5MB。

所有新增模型文件按固定官方metadata逐一校验LFS SHA或Git blob ID。首次大权重HF下载超时、镜像仓Python文件与固定HF版本不一致均保留；后者被拒绝执行，最终仅相同LFS权重允许官方镜像下载，代码/配置取固定HF版本。依赖下载镜像用于准备，MinerU109个、Monkey65个PyPI安装文件与官方PyPI SHA核对；Torch另12个安装文件核对官方来源。无凭据挂载。锁文件是**实际已安装环境快照**，构建配方主包固定，未来重建仍需核对完整快照与新镜像ID，不能假定依赖解析永久相同。

实际实验镜像 ID：

- Paddle `sha256:cb90de65a52f53707a05e26e0e8cfb09622e9001adde93f0359f15eaf8e23f56`
- MinerU `sha256:710f47d0fbe3b059394bc7e5f0b1429723459a007f37b12d53c6626443fa4039`
- Monkey `sha256:4e1dab1610ca1cfccb77809e72c9fa70122c0b859d9f2d4ec6281c339595b599`

GLM-OCR、Docling、Marker仅保留后续候选，本轮未部署、未调用。

## 3. 资源、真实运行与失败

宿主Xeon E3-1270v5（4核8线程、AVX2），约31,023MiB内存。每轮前可用约24,183–25,052MiB，负载约0.02–1.63；初始磁盘约295GiB可用，准备预留20GiB，模型约数GiB，未资源不足。无可用CUDA/nvidia设备；不使用GPU。宿主已有swap不作更改，各实验cgroup `memory.swap.peak=0`。

三个候选顺序执行，独立容器2CPU、16GiB、memory-swap总额16GiB，根只读，用户1000，cap-drop ALL/no-new-privileges，输入/模型只读，network none，无生产目录写权限；加载180秒、每页300秒，不扩容或延时。detached容器及逐页落盘避免终端断连重跑。续跑只跳过相同输入SHA的成功页，归档此前未完成尝试；并发输出目录锁的功能仅经合成测试。

| 真实尝试 | 导入秒 | 加载秒 | 整次墙钟秒 | 进程峰值RSS KiB | 容器峰值字节 | 状态 |
|---|---:|---:|---:|---:|---:|---|
|Paddle pilot-1|0.00017*|43.107|344.246|9614148|11510177792|12页300秒超时，未导出整页|
|Monkey pilot-1|1.539|4.675|306.947|8312708|8415035392|12页300秒超时，未导出整页|
|MinerU pilot-1|0.479|0.110**|2.040|196112|149860352|只读模型目录.lock创建失败，未识别|
|MinerU pilot-2|0.570|0.139**|11.038|1308836|1345224704|12页成功|
|MinerU remaining-1|0.385|0.086**|46.741|1532796|1601556480|其余9页成功|

*Paddle只是导入既有包装器，实际重依赖导入包含在build_pipeline加载区间，不能与另两者导入计时直接比较。
**MinerU为构造器计时，不是完整权重加载；实际ONNX session惰性初始化在首张，pilot-2依次为Magika0.032、检测0.047、识别0.099、布局1.288秒，完整列表见metrics。OCR/布局实际线程2/1；Magika辅助分类器官方固定4/1，仍受容器2CPU总额限制，不能声称所有组件线程均为2。

累计容器CPU时间/墙钟：Paddle345.772/344.246秒约1.00核；Monkey604.964/306.947约1.97核；MinerU成功两批17.432/11.038约1.58核、89.180/46.741约1.91核。MinerU逐页CPU秒见receipt，RSS为累计高水位；各页独立容器峰值未测，不能把批次峰值当每页峰值。全部无OOM、swap0；VL约10.72GiB、Monkey约7.84GiB容器峰值，明显高于生产4GiB额度，且仍未按时完成。MinerU本样本最高约1.49GiB不代表整册或正式Worker总内存可保证低于4GiB。

最小环境修复：MinerU源码在查找本地模型前仍需创建锁，首次Errno30有完整堆栈；只给隔离容器 `/models/.locks` 单独1MiB tmpfs，其余模型仍只读，没有伪造下载完成标记。随后成功。不修改生产/包源码。额外输入shape诊断首次observer误用list.shape失败，改用np.asarray取shape后独立诊断通过；页12 Markdown与pilot-2字节一致。该额外调用不混入十页性能统计。

Monkey真实试跑完成版面生成和少量区域文字后超时；初版观察器有并发ID/共享PIL编码问题，保存的raw-generations只完整保留两条成功调用，不代表全部区域响应。已修复为锁+局部ID+图片副本，24并发合成回归通过；**没有重跑真实Monkey整页验证该观察器修复**。完整stdout/stderr、部分原始生成、超时回执仍保留；不得把部分文字当整页成功。

## 4. 图片处理、原始产物与最小JSON

外部输入全部同一1819×2573 PNG，不在适配层纠错、缩放或有损重编码。各后端内部分别处理：

- MinerU把PNG包装为PDF，原生页尺寸654.8400×926.2800pt；额外页12实测布局tensor `[1,3,800,800]`，检测按块裁切/缩放，识别 `[batch,3,48,width]`，宽度320–2067。仅记录该页实际feed形状，不外推其他页。
- Monkey官方max_pixels=1003520，实测版面输入842×1191、一个已完成文字区域640×51；准备后的图片及哈希保留。并非原尺寸直接进入视觉编码。
- Paddle另做预处理器shape诊断成功，实际pixel_values `[5040,3,14,14]`、grid `[1,84,60]`；这只是单次诊断，不是整页管线全部区域的精确输入追踪。新PaddleX类名变化只适配诊断脚本导入，未静默补丁模型推理。
- M3历史请求提交原始PNG base64，源文件与实际提交字节、尺寸、哈希相同；服务内部处理未知。没有使用view_image，也未从成功提交推论服务保留全部像素。

每种方法独立目录：`page-N/raw.md`、`receipt.json`，MinerU还有原生`middle_json.json`、`model_output.json`、`structured_content.json`、`full-mode.md`及可能图片资源；运行尝试子目录保留metrics、完整stdout/stderr、阶段和终态。M3保存每次原始JSON及原样转写，136两次失败均保留。超时/未运行的方法明确缺少原生整页JSON/MD，不生成假输出。

各目录同级`content.md`与`structure.json`包含文档ID/原件SHA、物理/印刷页、图像SHA/尺寸、稳定块ID、原生类型/文字/顺序/图像引用/坐标/状态。合并Markdown仅加物理页注释作为传输分隔，原段文字原样；格式适配独立，不覆盖原始文件。

MinerU直接采用官方structured export的块顺序及bbox；安装包DocVortex schema.py和visualization.py证实bbox为[0,1]归一化xyxy、左上原点。原生中间树和包装PDF尺寸保留，不伪造像素定位。M3没有原生文字坐标/块类型，统一为一段未分块转写，坐标null；错误/未跑页diagnostics=null，不以零报警代替未知。

**默认MinerU Markdown过滤部分页眉、侧栏和页码，完整模式及原生JSON保留。**适配JSON采用原生structured blocks，不把默认Markdown过滤等同模型遗漏。不补到页末或猜题块归属；没有开发跨页语义合并器。并排查看可见M3有时保留更多页边字符，两者正文统计口径不因此混淆。

## 5. 实际核对与CER

程序对十页检查状态、空输出、题号/选项前缀候选、重复长行、重置、原生结构与文字原样映射；MinerU十页均有非空原生和MD，M3七页非空。没有检测到长行完全重复不代表没有近似重复或漏行。题号重置、前缀数量仅作提示，不作为已核实题目/选项总数；没有取消检查来消除困难页告警。

开发侧查看选页缩略图、印刷页脚及重点原图裁片，核对10页第32题、23页可确认选项、12页标题下题干及81页材料/小问。不是逐字检查十页，更没有用户人工验收。已看到：

- MinerU第10页第32题旧OCR漏掉的开头在输出中存在；174字符核对仅有1个标点编辑差异。9/10页跨页内容分别保留，跨页归属没有自动认证。
- 第12页相对清晰文字仍存在个别形近字误读（地名中的字）；不能因整体流畅称正确。
- 第23页MinerU出现题号/选项前缀异常、形近字错误，M3也有题号重号候选和无法辨认标记。严重困难内容仍需看原图，不用两者一致或M3流畅作真值。
- 第81页多选到材料题标题、材料1/2及小问存在；可见标点差异。没有声称所有长材料文字正确。
- 第168页MinerU题号末项出现回退候选，需用户对照；仅程序提示未计作已人工确认错误。
- 136页历史M3两次HTTP500，原始`api_error`/`output new_sensitive (1027)`如实保留，**不推断具体词语或拒绝原因**；MinerU本页完成不等于所有字正确。

CER复用可追溯看图参考，本轮重看相应原图裁片，不以M3输出作参考。标注均为“开发侧看图核对，未经用户确认”。仅去空白，大小写、标点、全半角均保留；位置按原生框和明确选项边界取出，没有搜索最优匹配来挑好结果。

| 相同区域 | 参考字符 | MinerU编辑数/CER | M3编辑数/CER |
|---|---:|---:|---:|
|23页两块可确认选项|66|2 / 3.03%|0 / 0%|
|10页第32题题干|174|1 / 0.575%|历史缺失，不可评估|

第23页历史排除217个无法可靠辨认字符，不能把66字符CER称整页错误率；保留原参考、不猜补。VL/Monkey未完成整页，CER不可评估，不填0。MinerU所有可用参考合计240字符3编辑，但与M3只有66字符不能作为不等范围胜负。参考来源SHA：offline-review-r1/reference-v2.json `012ef8edeadf4888c36bb2884b657d15b95cc62d2ede3daf6abe87293d1604af`；comparison/annotations-runtime-repair.json `b93e3e2d8d3d05621ceb912ca6d97ea70430d4bf5121696cecf16212fe3ce7de`；实际新抽取与评分在包内evaluation，历史字段与本轮字段分开。原件和原OCR未修改。

## 6. M3用量、验证边界和建议

本轮新增云端调用0、无新增推理费用。选定历史8页共9次请求，含两次失败，历史墙钟合计93.754秒。七次成功可见input_tokens26558、output_tokens4981、cache_read_input_tokens896、cache_creation_input_tokens0；失败未返回usage，不能填0费用或当全部费用已知。本轮不重新估算套餐费用、不读取凭据，模型下载网络成本与云推理区别。

真实：三个固定CPU环境、模型下载校验、离线加载/试跑、MinerU十页推理/导出、历史原样复用、原图局部核对、有限参考CER、离线浏览器十页切换/图片/原文DOM相等检查。模拟：15项适配、并发捕获、续跑、超时、输入校验回归。未验证：VL/Monkey完整页质量和吞吐、修复后真实Monkey观察器、十页逐字人工正确性、表格/公式/插图、整册和50页性能、生产沙箱接入、用户Windows阅读体验。真实浏览器检查不替代正文看版或逐字核对。

建议优先让用户查看 **MinerU Basic与历史M3并排结果**，之后可考虑扩大MinerU到50页，重点保留困难扫描与材料题。当前CPU成本较低且MD/原生JSON/坐标齐全，值得继续；但23页错误和默认导出过滤必须保持可见。不要因此定为最终后端，也不能以66字符推断整体优于或劣于M3。VL1.5 native Paddle及Monkey当前2CPU配置不适合本机300秒限时整页批处理；其他CPU引擎、VL新模型或GPU是未验证后续路线，本轮不扩展。GLM-OCR/Docling/Marker暂不部署。

## 7. 入口与交付

通用入口：`prepare_ocr_comparison_assets.py`（固定revision下载校验）、`audit_ocr_install_report.py`（官方包哈希核对）、`run_ocr_backend_comparison.py`（单后端/单页/断点）、`ocr_backend_comparison.py`（原样适配/合并/离线包）、`browser_smoke_ocr_comparison.py`（可选开发浏览器验UI）。不是正式FileTools受限调用或QQ交付，不能用于声称生产能力接入。生产Skill不改。

私有持久证据根：`/home/chen/dev/openclaw-filetools-dev/runtime/paddleocr-vl-evaluation/backend-comparison10-r1`；含research官方快照、models固定manifest、environment实际安装与哈希审计、results完整运行证据、evaluation看图参考及抽取记录。原图、正文、模型、完整响应不提交Git。

离线包解压打开`index.html`，切换物理页、点击原图放大；右侧原样文字，失败/缺失明确显示，原始JSON和日志在候选同目录。无审核表单、账号或Web服务。共享交付和包SHA见同目录[交付清单](evidence/ocr-backend-comparison10-delivery.json)。交付目录位于Chen/FileTools-Deliveries，独立于Incoming且未挂载给Agent作为incoming来源。等待用户查看，不自动开始50页或生产部署。
