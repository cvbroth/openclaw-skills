# MinerU Standard本地CPU两页实验（2026-10-08）

本轮两页均完整完成，页面处理约5.78／4.82分钟，结构及可读性较Basic有收益，仍有关键误读；不据此认定优于M3或接入生产。

基于8cf887ddb335bf2ad412c5fd210c7d98083bbd2f，保留此前Basic、VL1.6、Monkey和M3原始历史结果、外层整册工作区。仅物理12/23页；无新云调用、凭据读取、生产安装/部署/配置/Skill/模板更改、整册OCR、正式Word/PDF、saved保存或入库。

## 真实路线与固定身份

[官方档位说明](https://opendatalab.github.io/MinerU/usage/tiers/)和[模型来源说明](https://opendatalab.github.io/MinerU/usage/model_source/)明确支持CPU环境的ONNX小模型＋llama.cpp；Standard需VLM，Basic无VLM。本轮沿用已安装MinerU4.0.10，真实`MinerUParser(tier='standard',parse_mode='ocr',image_analysis=True)`映射effort=high。不是改名Basic，也不是调用云端解析API。源码证据保留在私有research/mineru-installed，关键为parser/tier.py、model/registry.py、model/vlm/{client,runtime,selector}.py、backend/analysis/pdf/window.py。

- 镜像sha256:710f47d0fbe3b059394bc7e5f0b1429723459a007f37b12d53c6626443fa4039，复用Basic镜像，不覆盖生产标签。
- MinerU4.0.10、mineru-vl-utils2.0.5、mineru-llama-cpp0.1.2、DocVortex0.5.10、ONNXRuntime1.30.0、NumPy2.5.3；完整freeze复用deploy/ocr-comparison-locks/mineru.txt。内置llama-server实际`version: 1 (9a3bf2b)`，GNU14.2.1/Linux x86_64；不是另装系统llama-server。
- VLM为MinerU registry指定的[GGUF仓库](https://huggingface.co/jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF)，revision9185688a0495e1577d521a757c7c0b62dd38ca48。仓库归属jinzhenj，不能写成OpenDataLab原始safetensors；对应[原始模型名称](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B)为MinerU2.5-Pro-2605-1.2B。与之前Paddle/Monkey权重不同。
- 主GGUF531066496字节，SHA3f3523429c880d675c0330cb3de78240452bc40a961d037e24f91ab8488f03e7；mmproj709409600字节，SHAb6c08ab50352677f7396af45ee60682f353f55488e26911d8154bfc37514d3f8。新增下载总1240476096字节（约1.16GiB）；没有下载另一套未经使用的safetensors。
- GGUF头及tensor描述实际检查：主模型494032768元素，mmproj661993856元素；合计约1.156B。二者包含Q8_0及F32 tensor，不能称全部float32或仅0.5B模型。主290 tensors（169 Q8_0/121 F32），投影520（194 Q8_0/326 F32）；GGUF metadata量化版本2。运行算子累加精度未单独探测，未知。
- 小模型沿用opendatalab/MinerU-4_models_onnx revision358310b4f64b95f9fefc372ad899356e4111f376；本轮重新验证已有14文件字节数及SHA，不重下载/修改。实际ONNX session、provider和threads在每次metrics；包含PP-DocLayoutV2、PP-OCRv6检测及识别初始化。初始化某模型不等于最终正文由该模型生成；真实逐区域Engine响应证明本轮使用VLM。

固定身份、权重及资源边界见[evidence/mineru-standard-fixed.json](evidence/mineru-standard-fixed.json)，GGUF元数据/tensor统计见[evidence/mineru-standard-gguf.json](evidence/mineru-standard-gguf.json)。资产用既有流式脚本按固定远端元数据SHA校验，再由官方下载流程固定revision、校验并生成完整标记；未手造完成标记。准备阶段一次无网络路由失败、两次连接无进展后停止，最终修正既有开发代理的小写变量传递，官方流程完成；不输出代理值，不挂载认证目录。推理完全断网。

## 输入与运行边界

授权原件`/srv/storage/users/chen/FileTools-Incoming/27版肖1000试题分册.pdf`只读重新核对SHA：0007677dc510b01ffed36bd1250fafd8a7b0101f383e3603257b45e379a6f28b。只复用两页220dpi RGB PNG，与前三轮字节相同：

|物理／印刷页|尺寸／字节|PNG SHA-256|
|---|---|---|
|12／7|1819×2573／2254983|81d706884884e0610632493c29b56250aea4fc164096c7db6b10026a8ebc034c|
|23／18|1819×2573／1891843|10eca256252fed33100c29c5ad5163555a01cf3b6c1f0e3d2be6c87bb1422742|

宿主Xeon E3-1270v5、4物理核/8逻辑线程、无可用CUDA；开始前MemAvailable约24981MiB、load0.33、磁盘280GiB空闲。宿主已有swap不变；每个推理容器2CPU、16GiB，memory-swap总额16GiB、无额外swap。nonroot1000、根只读、cap-drop ALL/no-new-privileges、network none、原图/源码/模型只读、仅独立结果目录可写，模型锁独立1MiB tmpfs；加载180秒、单页1800秒。先12完成，再23独立冷启动；Docker detached后台、逐页落盘，未靠SSH会话维持任务。

局部运行适配显式传官方Engine支持的n_threads=2、n_gpu_layers=0、n_parallel=1；官方默认分别为-1/99/4。配置max_concurrency=1、LLM辅助关闭、server_url为空。实际文本采样temperature0/top_p0.01/top_k1、presence_penalty1/frequency_penalty0.05/repeat_penalty1；未额外设置max_tokens，沿用官方EOS/8192上下文终止。无长度截断，但不据此证明全文无漏行。安装版本YAML没有这些Engine字段，因此仅在研究进程构造时包装，不伪造配置项或修改安装包源码，不换推理管线。ONNX识别/布局实际2/1线程；Magika辅助分类官方固定4/1，仍受容器总2CPU配额限制。不能声称所有组件都只有两个线程。

首次第12页观察器初始化1.004秒失败：误将prepare_for_extract定位到MinerUClient，实际属于MinerUClientHelper；完整AttributeError/零业务输出保留在trials/page-12/attempt-history/attempt-1。修正后重试，不更换模型/输入/资源或挑选识别最好的一次。26项合成回归覆盖原图字节保持、官方调用参数/返回保持、脱敏摘要、历史适配、并发观察器和watchdog；另修复续跑归档后旧终态回执残留的问题。

## 内部输入、保存及追溯

外部不改PNG清晰度。实际工具链为PNG→DocVortex.from_image包装PDF（Pillow PDF quality95/subsampling0）→200dpi内部页图→ONNX布局→按normalized bbox裁片→官方prepare_for_extract尺寸/旋转规则→PNG data-URI→本地Engine。源输入220dpi不代表管线无内部重编码；本轮明确披露包装PDF有有损图像编码。内部页实际1820×2574，与源1819×2573有舍入差异。

Standard/high使用ONNX布局后batch_extract_with_layout，不额外用VLM生成整页布局（Advanced/xhigh才batch_two_step_extract）。Helper可将极端长宽比padding、短边不足28放大、按angle旋转；实际各次裁片尺寸/MIME/文件字节SHA保存于raw-generations/*/receipt.json，按客户端已有data-URI解码保存，无重复resize或再次推理。mmproj元数据image_size560/patch14不是实际所有输入都560×560的证明；C++视觉编码器进一步张量缩放/裁切未单独测量，未知。

每页保留原生middle_json.json/model_output.json/structured_content.json/Markdown、full-mode.md、资源图，另存每次Engine原始messages/采样参数/GenerateResult/content/finish_reason/token/内置timings及实际输入PNG。native Markdown自身的排版/过滤与开发适配分开；默认可能过滤页眉/侧栏/页码，完整模式与原生JSON保留，不称底层未识别。模型原文未润色/补写/知识纠错。

统一content.md/structure.json复用既有适配，源PDF/物理印刷页/源图片SHA、稳定块ID、原生类型/文字/顺序/资源和坐标保留；MinerU bbox为包装PDF的normalized xyxy[0,1]，原生point尺寸及内部页尺寸独立保留。不是原PNG像素坐标，未做独立像素对齐验收，不能将此坐标写成已核实题目框。未提供字段不编造；M3无原生文字坐标，null；Monkey23保持未完成/部分展示标识。

私有根`/home/chen/dev/openclaw-filetools-dev/runtime/paddleocr-vl-evaluation/mineru-standard-two-pages-r1`；源码/模型研究、输入、trials和results持久保存，不使用短期FileTools任务缓存，不扫描其他NAS文件。推理原始响应、图片、全文和模型权重不入Git。

## 第12页完成结果与局部看图检查

12页页面处理346.878秒（含惰性模型加载/解析/导出/观察器），进程总墙钟349.034秒，页面进程CPU687.199秒、容器CPU691.004秒，平均约1.98核；进程峰值RSS2476168KiB（约2.36GiB），容器memory.peak2101342208字节（约1.96GiB），swap0/OOM0，完整SUCCEEDED，无生成截断。

包导入0.407秒，parser构造/观察器安装0.777秒（不是全部加载），VLM实际加载1.232秒，ONNX初始化合计约1.054秒；window_prepare含渲染/布局/ONNX等1.913秒。10次VLM调用累计340.577秒，内置prompt_ms合计308.297秒、predicted_ms合计32.047秒，生成900 token，逐调用返回合计1397字符；默认MD1386字符、原生10块。native save0.075秒，额外两种Markdown序列化时间未单独测，未知。data-URI捕获合计0.0144秒，仅此项开销可测，不代表总观察器开销。

计时不可嵌套相加：window_prepare包含ONNX加载；Engine.generate包含视觉处理/提示处理/生成，内置prompt/predicted为其内部口径，prompt_ms不是已独立测出的视觉编码器时间。没有将两者相加后再加入generate。独立布局网络纯算子耗时、独立视觉encoder/采样开销未知，不编造。所有历史性能只作其原实验条件对照，不将暖进程Basic23页与当前独立进程直接当同口径benchmark。

|局部／组织|本轮原始结果与原图结论|
|---|---|
|41题指定短语|“就湖治湖”匹配；与此同时，同题专名中的“素”变成“索”，在多处重复出现，不能因一个锚点正确称整题准确|
|45题D|“预想的结果”匹配；历史M3这里为“预期的结果”，M3不是真值|
|42/43/44/45/46题|选项与题干分行，较Basic全部粘在段落末尾便于阅读；42选项仍同行，43等分行，不自动强制改写模型格式|
|41题|题干尾与A选项仍同一行；不能声称所有题干/选项都已正确拆分|
|章节与顺序|章节在42与43之间，41–46依序可见，A–D前缀各6，长重复行0；后两项是程序模式检查，不是逐字/归属验收|
+
+局部核对为开发Agent看原图及放大裁片，不是用户人工认证；未建立两页逐字参考、未计算整页CER/准确率。源23损伤区域不可凭语义补原文。

## 第23页完成结果与局部差异

23页页面处理289.061秒，进程总墙钟290.877秒，页面进程CPU572.577秒、容器CPU576.116秒，平均约1.98核；进程峰值RSS2420396KiB（约2.31GiB），容器memory.peak1949233152字节（约1.82GiB），swap0/OOM0。原生整页SUCCEEDED，无超时/主动中止/生成截断；13次Engine调用均返回stop，非仅部分文本。

导入0.389秒，parser构造/观察器0.522秒，VLM实际加载1.214秒；window_prepare含布局等1.880秒，13次Engine.generate合计283.295秒；内置prompt253.954秒、predicted29.134秒。累计生成867 token、原始逐调用合计1315字符，默认MD1272字符、原生13块，native save0.0678秒；capture0.0144秒。独立视觉编码耗时仍未知，不能将prompt阶段直接改名视觉encoder。两页都是独立进程冷加载；未清空宿主文件页缓存，不称磁盘冷启动。

|核对项|实际结果／边界|
|---|---|
|122题否定句|原始输出包含“不足劳动”，保留“不”但相关源字形受损；不将整句认证为正确，也不凭常识替换成预期词|
|123题|四选项按A–D分行，与Basic乱码和编号粘连相比更易对应；A把可辨“增殖”转为“增长”，C仍有破碎文字；部分修复可读性不等于完整正确|
|124题|四选项齐且依序分行，但题干“弱于”、B/D“恍食”等仍异常；源图局部不可靠可辨处不建立确定替代真值|
|125题|本轮号码125与原图可辨号码匹配；历史Basic此位置为126。该处与下一块的源图号码疑点区分|
|125与127之间的号码|程序检出128→127→128回退/重复，但源图该号码本身就接近128。上一轮“清晰原126被OCR变128”的断言证据不足，已追加更正，原历史记录保留。不按正常题序推改号码，不把这一告警强行归为新模型错误|
|127题|B“最低劳动强度”可辨段匹配，“一旦”保留；A仍有错字，未认证整题所有字符|
|128题|B的“不得不”保留；C/D将可辨“基础”转为“范围”，同时存在“基于”转“由于”等，不能以流畅度通过；不可辨字仍未知|
|组织与顺序|原图横排选项转为A–D分行，九个正文版面区域按空间顺序输出；129选项仍同行，未自动重排或规范化。没有将版面块坐标冒称每个选项独立坐标|

程序检查：题号候选[122,123,124,125,128,127,128,129,130]，A/B/C/D前缀各9，长重复行0，号码回退1。只证明这些模式存在，不能证明九题逐字正确、选项归属或源图所有文字完整。13原生块含页眉、侧栏、页码和页脚，默认MD过滤其中部分，完整模式及原始响应保留；不存在开发侧把所有原始行拼页末的“恢复”。

已查看两页整图及指定局部裁片，并逐项阅读返回的题干/选项/原生布局对应关系；不是两页逐字真值认证。困难页损伤仍限制辨认，无法确定的内容没有用知识/其他OCR补齐。坐标未做逐像素独立准确性验收，未覆盖其他页、跨页题、表格/公式/复杂多栏或完整题册。

## 对比、验证和建议

|路线|物理12／23实际页面处理|本轮定位|
|---|---|---|
|MinerU Standard 本轮|346.878／289.061秒，均整页完成|ONNX布局＋独立MinerU Q8_0视觉模型；本轮真实新运行|
|MinerU Basic 历史|9.672／4.385秒，均完成|无VLM；23页明显乱码，正文与选项经常粘连；23为旧同进程后续页|
|PaddleOCR-VL1.6 历史|1015.088／713.368秒，均完成|native Paddle CPU，约9GiB RSS；本轮仅逐字节复制历史，不重跑|
|Monkey 历史|439.681秒／主动中止、仅部分输出|约6.49GiB RSS；23无完整原生最终MD/JSON，保持失败标识|
|M3 历史|10.338／12.417秒，远程历史请求|仅复用原始图片直传历史；服务内部图像处理未知，本轮调用0，不能与本地CPU当同算力benchmark|

Standard相较Basic确有组织和可读性的收益，但仍不能证明整页逐字准确，也没有证明全面优于历史M3。两个指定12页锚点匹配不抵消专名错误；困难23仍有词语/数字疑点。现阶段不更换正式OCR，不扩大样本，也不自动开启速度优化。建议先由用户查看本包确认质量收益是否足以接受；若认可，再单独授权提速实验。本轮不转测GLM/其他项目。

当前CPU路线可运行，平均接近2核，两页均明显低于16GiB上限；单页仍约5–6分钟，远超生产临时脚本60秒。RSS与cgroup peak口径不同，不相加、不据其中一个直接保证4GiB生产Worker可用；生产模块/并发/长期运行及受限入口均未验证。无需据本轮加内存，亦未调整生产4GiB/超时/权限。

真实验证：两页官方Standard完整运行、同字节输入/固定权重校验、实际CPU/cgroup资源测量、原始响应和原生导出、局部源图对照；浏览器真实file://检查两页五路切换、原图尺寸、所有可用原始MD在DOM中SHA相等、无JS错误/外网请求/横向溢出。浏览器仅验证展示机制，不认证模型文字或用户客户端体验。

仅代码/合成：26项回归及Ruff、diff检查通过；覆盖data-URI字节/尺寸不变、支持参数、原调用入参及返回不变、脱敏摘要不泄露原文、失败归档/成功页保留、既有适配及watchdog。初次观察器完整失败记录与三次未完成网络准备的现有证据保留（初次网络stderr仅工具回执，未单独完整落盘；两次无进展日志为空，另有操作记录），不从完成率中隐去；真正模型推理的两页各一次成功，无重试挑最好结果。

未验证：逐字整页准确率/CER、源损伤字真值、模型猜补与误读的全部区分、独立encoder耗时、内部视觉tensor精确缩放、坐标像素对齐、其他硬件/线程/并发、全册容量、生产FileTools60秒兼容、QQ正式交付、用户客户端下载及看版。原生引擎还发出Qwen-VL grounding最少image-token建议及control-token类型警告，完整日志保留；未证实为本轮错误根因，未据此改采样/图像参数。

## 交付与停止点

私有原始输入、模型、完整响应和裁片保留在本轮忽略目录。`delivery-final/index.html`复用既有离线界面，按物理页切换、点击原图放大，展示本轮Standard及四路历史；各方法同目录有content.md、structure.json和page-N原生文件。单页model原文在raw-generations/*/{response.json,text.txt}，客户端实际裁片也在其中；不要只看经过工具格式化的默认Markdown。原生导出/完整模式、环境与资源日志共同打包；模型权重不入包。

包中只含物理12、23原图/历史结果；Monkey23始终为标识明确的部分展示，未虚构其完整结果。无审核状态系统、RAG、自动路由或质量评分。共享交付清单及确切SHA见[evidence/mineru-standard-delivery.json](evidence/mineru-standard-delivery.json)。本轮到两页交付停止，等待用户查看，不自动扩页/部署/生成正式题册。

已复制核验：服务器 `/srv/storage/users/chen/FileTools-Deliveries/mineru-standard-two-pages-20261008/filetools-mineru-standard-two-pages-20261008.zip`；Windows `\\myserver\Chen\FileTools-Deliveries\mineru-standard-two-pages-20261008\filetools-mineru-standard-two-pages-20261008.zip`。包大小27795295字节，SHA-256 `2e756c8d430b92fe8abb0dc1f97bbf83bcb538eae202f62a5a3b9222ce859f4d`；复制SHA及ZIP CRC通过，目录不挂载给Gateway/Worker、incoming仍只读。客户端实际下载/用户看版尚未验证，不能写成QQ正式交付。包内REPORT为打包前版本，外部Git回执记录本最终哈希。
