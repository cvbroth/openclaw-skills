# VL1.6整页CPU实验（2026-10-08）

本轮真实VL1.6原生Paddle CPU完整管线在物理12、23页均完成；这证明可运行，不证明逐字正确，也不证明本机适合批量处理。沿用01a7a406727f89ad72fdf46c1aab58b0b554c133测评分支及十页实验，保留原结果、外层整册成果和生产部署。本轮固定物理12页成功后再串行测试23页；不自动扩展十页，不继续扩大MinerU或修补传统OCR正文。

## 官方路线及固定身份

[官方VL指南](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md)明确区分布局+VLM完整管线与单独VLM，并提供x64 CPU的Paddle/Transformers路线；没有把GPU服务的客户端当作CPU模型。本轮选已有native Paddle完整管线，不另外铺开Monkey或新项目。软件包3.7.0/PaddleX3.7.2/PaddlePaddle CPU3.2.2/NumPy2.3.5；镜像沿用sha256:cb90de65a52f53707a05e26e0e8cfb09622e9001adde93f0359f15eaf8e23f56，未重建生产。

真实1.6权重来自[官方PaddleOCR-VL-1.6仓](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6)，revision c5630abae1d940eafe0697512a0325494b02ab42；model.safetensors 1,917,255,968字节，SHA85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db。与1.5 SHA d557c9d8…不同；不把升级包等同升级模型。所有文件逐一核对固定官方metadata哈希。官方README链接的ModelScope仅用于相同LFS权重，配置/代码取固定HF版本。官方layout仍为既有PP-DocLayoutV3固定权重，不称1.6布局新权重。没有下载或运行别的云端模型。

源PDFSHA0007677dc510b01ffed36bd1250fafd8a7b0101f383e3603257b45e379a6f28b本轮重算一致。12/23页仍为同一1819×2573 RGB PNG/220dpi，文件字节与十页实验一致。没有降低输入质量或预处理困难页。官方管线仍按布局裁切区域，并按min_pixels112896/max_pixels1003520等内部策略缩放；实际每区域crop shape、array-bytes SHA及视觉patch/grid形状写入phase-events，不将源PNG尺寸冒称全部内部模型输入尺寸。

## 上轮耗时定位与本轮参数

原300秒日志只证明加载完成并进入page阶段，缺细阶段计时，不能事后编出视觉/生成时间。原累计容器CPU345.772/344.246秒约一核。新增120秒同配置诊断（VL1.5、2CPU、16GiB）单独保存：首次观察器受到Paddle自有forward包装的self注入影响失败，已读安装源码，修正为bound MethodType；保留堆栈，不计模型失败。复测布局4.208秒、10区域，首个小区域视觉16.668秒、生成含视觉21.780秒、9个语言步；第二大区域视觉编码在120秒截止仍未完成，只有首区域原始输出，未组装成整页。

[官方线程flag说明](https://paddlepaddle-static.cdn.bcebos.com/documentation/docs/guides/flags/device_cn.html)默认FLAGS_paddle_num_threads=1；独立镜像实际get_flags及诊断metrics确认1。cpu_threads=2用于静态布局，不代表动态图VLM是2。本轮显式FLAGS_paddle_num_threads=2，OMP/MKL/OPENBLAS=2，2CPU配额，16GiB内存/memory-swap总额16GiB、实际两页swap峰值均0；不是生产4GiB额度。flag=2不等于实际CPU会用满两核，报告依据累计CPU和阶段CPU/墙钟。

宿主为Xeon E3-1270 v5（4物理核/8逻辑线程、AVX2），约31 GiB物理内存，无可用CUDA GPU。启动12/23页前实际可用内存分别24758/24799 MiB，load约0.84/1.01；根分区约282 GiB空闲。宿主既有swap未修改，实验容器memory-swap总额等于内存额度，终态swap峰值0。宿主内存不等同生产Worker额度。

单页最长1800秒、加载180秒。后台detached容器断网/只读根/原图模型只读/nonroot/cap-drop ALL/no-new-privileges，5秒一次资源快照、逐区域事件、原始生成token和原始区域结果落盘。源权重下载在准备阶段进行；Docker准备缺curl/桥接无外网/宿主网络直连超时均保留日志，最终主机既有curl仅下载公开模型到开发目录，未安装生产依赖。下载器新增流式哈希和无curl的有界标准库fallback，不读取业务资料。

重复生成早停规则：至少512个已观察单token decoder输入且末64token连续重复4次则异常终止；属于实验停止规则，不是质量评分。未观察到token时不以零token宣称卡死；视觉编码耗时长但CPU持续活动仍等待有界截止。模型返回的每区max_new_tokens=4096、use_cache=True及实际shape/步数保存；达到上限或异常重复须单列，不能只看API退出状态。

## 输出与验收口径

完整页才适配原生parsing_res_list的block_content/label/bbox/order；坐标保留原生源图像素xyxy，未提供时null。原生JSON/Markdown保留，统一raw.md仅逐字节复制原生MD，格式适配独立。部分区域结果、decoder-input token片段不会伪装成整页content.md。各候选目录同级content.md/structure.json及原始尝试日志；历史M3两页只复制既有原响应，不发请求，不用作参考答案。

本轮不计算未经看图参考的整页准确率、不润色纠错、不拼猜遗漏、不新增质量评分/审核状态/RAG/路由。原始OCR、原图、模型全文和完整响应仅在忽略目录。既有Word/PDF模板不变，无正式题册生成、生产部署、saved保存或知识库导入。

CPU路径源码补充：安装的PaddleX doc_vlm/modeling/paddleocr_vl/_siglip.py:185–201在float32条件下使用eager_attention_forward，:111–123为显式matmul/softmax/matmul；这说明本次不是GPU融合注意力路线。尚未做算子级profiling，不能把耗时全部归因到某一个算子，或认定线程flag是唯一原因。两次权重版本不同，首区域16.668与15.475秒也不是线程数单变量A/B实验。

开发侧局部看图：第12页第一段长题的地名识别正确，但另一个四字短语中出现字形误读。仅是明确局部例子，保留原文，不计算整页准确率，不以M3或文字通顺作真值。对应原图与原始输出均留私有包，未经用户确认。

## 已完成第12页的真实测量

| 项目 | 实测 |
|---|---:|
| 构造/加载（含此处重依赖导入） |39.873秒|
| 整页识别+原生导出（含观察器） |1015.088秒|
| 整页阶段进程CPU |1017.275秒|
| 整个进程墙钟 |1056.127秒|
| 整个容器累计CPU |1060.993秒|
| 进程峰值RSS |9383972 KiB|
| 容器memory.peak |9430552576字节|
| 容器swap峰值 / OOM计数 |0 / 0|
| 布局分析 |3.015秒，10区域|
| 视觉编码合计 |565.760秒，10次完成|
| generate合计（含视觉，不能再与视觉相加） |1010.070秒|
| 扣除视觉后的其余生成开销 |约444.310秒；包含投影/解码/采样等，不称纯文字forward耗时|
| 原生生成token合计 |852；所有区域均未到4096上限|
| 原生JSON / Markdown |10块 / 3894字节、1411字符|

阶段是嵌套调用，不能重复相加。语言forward只有周期进度计数，末尾不足16步没有单独最终累计；不编造精确纯解码总时间。加载CPU未单独计区间，初始事件记录的是进程启动以来累计CPU，口径与加载秒不同。RSS含共享映射等，与cgroup实际计费内存不相同，不相加或硬比较大小。当前运行有观察器及原始区域数据序列化开销，非无观测纯模型benchmark。

原生宽高1819×2573，10区域均有原始区域返回及生成token文件，最终parsing_res_list为10块；全部有界调用和导出完成，status=SUCCEEDED。程序检查题号候选41–46、A/B/C/D前缀各6、长行完全重复0，与历史M3本页候选数量相同；不称已逐字/逐题正确，也不以数量相同排除错字。第一张成功后才启动第二张，两个单页进程各有独立冷加载，未将第二张当暖启动。

## 第23页终态与局限

| 项目 | 实测 |
|---|---:|
| 构造/加载（含重依赖导入） |41.312秒|
| 整页识别+原生导出（含观察器） |713.368秒|
| 整页阶段进程CPU |715.624秒|
| 整个进程墙钟 / 容器累计CPU |755.817 / 759.489秒|
| 进程峰值RSS |9377316 KiB|
| 容器memory.peak |9450954752字节|
| 容器swap峰值 / OOM计数 |0 / 0|
| 布局分析 |3.037秒，14个检测框|
| 视觉编码合计 |416.402秒，13次完成|
| generate合计（含视觉） |708.382秒|
| 扣除视觉后的其余生成开销 |约291.979秒，非纯解码时间|
| 原生生成token合计 |762；所有区域未到4096上限|
| 原生JSON / Markdown |14块 / 3664字节、1478字符|

status=SUCCEEDED，原生页宽高1819×2573。14个最终块包括一个footer_image，其内容为图像引用，无VLM文字生成；13个VLM区域全部有原始返回与token记录，非“漏跑一个区域”。原生图像资源也随结果保留。所有区域未到4096生成上限，无重复生成早停，终止原因均为正常完成。

程序检出题号候选122/123/124/125/128/127/128/129/130，一次回退；A/B/C/D带标点前缀候选8/7/8/7。原文一些前缀没有点号，所以计数差不能直接当作遗漏选项；开发侧本轮看图确认原题号126被转成128，构成一个实际题号误读；回退告警并非都是真实页面错序，未自动补改。没有取消告警或把此计数称核实题目数。

开发侧重新查看第23页原图和已有末题选项放大图：末题四个选项本次转写与该局部可辨文字一致；侧栏存在明显误读；其他区域仍有明显不通顺的原始输出和疑似字形误读。这里只确认该局部，不以语义猜测修正其余字，不给困难页整页准确率。扫描受损处未经可靠看图确认就不作确定真值。输出未润色、未补写，等待用户对照。

历史M3物理12/23页分别耗时10.338/12.417秒、1416/1277字符，记录为此前真实请求复用，非本轮CPU速度对照的同硬件测试；本轮新增云调用0。两页M3原始PNG提交字节/尺寸/哈希与本次源图一致，服务内部处理未知；M3没有提供原生块坐标，统一结构中为null。本轮不据字数或阅读流畅度判定哪路更准确、不用M3作答案、不新增CER或云费用。

## 代码、真实验证和未验证

- 增量入口固定真实1.6权重及模型名，显式CPU线程flag，新增有界阶段观察、5秒资源采样、重复生成早停；安装包源码未改。观察器SHA为01ad69311f378d22c2ac94a67e022aa0a40ba0f2062972196cf80dccdb00c83d，与两次使用的快照一致。
- 适配器只复制已完成原生MD、保留parsing_res_list及真实坐标/顺序；不从部分区域拼造完整页。下载器改为流式校验，容器无curl时允许有界标准库准备，不影响推理断网。
- 真实运行：两页各独立冷加载、完整原生导出、无OOM/额外swap；输入及权重哈希核对。源码/模型版本、原始阶段日志、区域crop和实际tensor/grid、生成参数完整留私有实验目录。
- 合成回归20项通过，含观察器MethodType绑定、重复阈值、流式校验拒绝改坏文件、原文/坐标适配、既有有界监视/模型清单；Ruff和diff空白检查通过。测试警告为既有SWIG类型弃用提示，不计模型故障。
- 未验证：两页逐字完整人工验收、整页CER、其他题型/其余八页/整册、无观察器纯推理速度、算子级瓶颈、相同权重线程1/2因果对照、Transformers/llama.cpp等其他官方CPU引擎、GPU性能、用户端离线包打开。恢复逻辑有合成测试，本轮未故意中断成功推理来宣称真实断线续跑已验收。

建议：当前native Paddle路线确实能在本机CPU完成整页，不再以旧300秒截止称“无法运行”。但本次两页约12–17分钟/页、约9GiB进程峰值，CPU实际仍近一核，明显超过生产4GiB额度；不建议直接用于当前机器批量/生产。没有证据把该成本推广到所有CPU引擎或承诺GPU具体速度。先请用户查看两页原始对照；若文字收益值得追求，再单独决定其他官方CPU引擎或GPU环境评估，不自动扩跑十页，也不启用Monkey作为并行新项目。生产、既有Skill、Word/PDF模板和整册开发工作区保持原状。

## 可复核交付

持久实验根为`/home/chen/dev/openclaw-filetools-dev/runtime/paddleocr-vl-evaluation/vl16-two-pages-r1`：

- `results/vl16-page12`、`results/vl16-page23`：每次真实运行完整原始产物、stdout/stderr、metrics、receipt、phase-events和资源采样；`results/vl15-profile*`保留诊断尝试及首次观察器堆栈。
- `results/paddle-vl16`：完成页适配；`results/m3-history`：源PNG哈希匹配的历史原响应。原生JSON没有footer_image的块级文件路径，统一image_references不猜造；MD实际引用和imgs资源仍在原生页目录。
- `delivery-final/index.html`：两页原图与两路原文；同目录候选content.md/structure.json及逐页原始结果。`trials`、`environment`保存尝试及固定身份，不含权重/凭据。

Chromium140.0.7339.16实际打开file://，12/23页切换、原PNG尺寸、两路原文DOM字节一致、无外部请求/JS错误/横向溢出检查通过。开发侧已查看第23页界面截图；截图字体仅在开发浏览器注入，不打包，用户Windows字体显示仍待查看。这是界面验收，不是转写准确率证明。原图和截图不入Git。

共享交付将在Chen独立FileTools-Deliveries下，非Incoming、非FileTools正式产物发布；大小及SHA另见`docs/evidence/vl16-two-page-delivery.json`。解压后直接打开index.html，选择12/23页，点击原图放大。客户端实际下载/解压/查看尚未确认。两页完成后停止，等待用户审阅；没有扩大十页/整册，没有生产、保存或入库动作。

共享包已复制并校验：

- 服务器：`/srv/storage/users/chen/FileTools-Deliveries/paddleocr-vl16-two-pages-20261008/filetools-vl16-two-pages-20261008.zip`
- Windows：`\\myserver\Chen\FileTools-Deliveries\paddleocr-vl16-two-pages-20261008\filetools-vl16-two-pages-20261008.zip`
- 18,629,359字节；SHA-256 `ae001d5daa9b5cf83279157423c981140544913718255c1e4f917ae54c0d6245`；复制前后相同，ZIP CRC通过，UID/GID1000、0640。
- 只读检查实际Gateway/Worker挂载确认FileTools-Deliveries不在其挂载下，Incoming仍只读；未进入或变更服务。包内REPORT为打包时版本，最终交付哈希见本附录/仓库证据，避免自包含哈希循环。
