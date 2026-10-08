# GLM-OCR 本地 CPU 两页实验与阶段选型（2026-10-08）

本轮未获得两页完整成功输出。物理12页首次调用原生 FAILED，保留1365字符部分输出；一次诊断重试因方案被上游证据否定而主动停止。物理23页遵循“先完成12页”的要求未运行。没有新增云调用、生产修改或扩大候选。保留 f4c85ad548ca8f9226a1f21a669a0a9dd4f86977 的全部历史结果及外层整册工作区。

## 真实路径与固定身份

[官方 GLM-OCR Ollama CPU 指南](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/examples/ollama-deploy/README.md)提供本地 CPU 路线。本次是本地 `/api/generate` 单张整图识别，不是 SDK 默认云端 MaaS，也不是 SDK 的 PP-DocLayout-V3 布局＋分区域识别流程；layout_model=null，无识别坐标。

- 模型：官方 registry.ollama.ai/library/glm-ocr:q8_0；下载时 manifest SHA256 `2a5a0f1a93017fc9db321ec196efb4b9bbba97c4d890df8e39429ed771f2ed25`。
- 原始 GGUF：1,588,187,104字节，SHA256 `24ca1840804a2aa3faeb2cadf31f628ec8bd48393cf1938c414f0e6cda81914a`。运行前后哈希一致。Ollama 分发标记1.1B，官方模型介绍0.9B；不把标签差异隐去或宣称独立验证了两者权重等价。
- 实际存储527个张量：114个Q8_0、127个F16、286个F32，共1,107,405,824个元素；运行累加精度未独立测量。
- 官方 Ollama 0.40.1，源码 `cf2a313a298066d572c36812e5ad30a21c0db13b`；官方 Linux amd64 包1,436,371,398字节，SHA256 `a7aebbe3dd76ccf1351a56a3e57218ad4863cb5f9a9938c58de87a37555e355d`。只提取官方CPU二进制/库；未改安装包源码。
- 实际 llama.cpp b11351 / `631109b34da437a3c4a5ebd75091d677671392e3`，CPU Haswell，0 GPU层。实验镜像 `filetools-ocr-compare:glm-ocr-ollama0401`，实际ID `sha256:43a40b1a8882cb77f4c2c8827f77f641a984a91ca16668a7afb6451cc1d17856`。
- 官方兼容转换首次13.924秒，生成独立模型/投影缓存：SHA256 `5836db6656f7cffea9c402c94da2ac5639db9c50c1f3bed18dc8e559bb17dfda`（719,168,576字节）和 `4d284133151aa52d14d505b0ed41200cd5527edb85029b502eac527618e9a6a2`（871,426,528字节）。原始 blob 保留，分发 manifest 副本保留；运行缓存 manifest 经官方迁移变化。全部blob运行后重新计算哈希。

下载与推理分开：网络准备曾遇代理停滞、Docker拉取停滞和公开下载超时；改为同一官方版本公开资产的有界续传并校验。主权重＋发行包约3.02GB，不含未完成下载和派生缓存；没有使用业务凭据或远程推理。

## 输入与限制

原PDF只读：`/srv/storage/users/chen/FileTools-Incoming/27版肖1000试题分册.pdf`，169页，SHA256 `0007677dc510b01ffed36bd1250fafd8a7b0101f383e3603257b45e379a6f28b`。复用前轮相同220dpi、1819×2573 RGB PNG，未重新OCR或扫描其他文件。

| 物理／印刷页 | 字节 | PNG SHA256 |
|---|---:|---|
| 12／7 | 2254983 | 81d706884884e0610632493c29b56250aea4fc164096c7db6b10026a8ebc034c |
| 23／18 | 1891843 | 10eca256252fed33100c29c5ad5163555a01cf3b6c1f0e3d2be6c87bb1422742 |

客户端base64解码后的实际提交图片与源PNG逐字节相同。原生模型仍有内部视觉预处理：实际日志min/max pixels为6272/3211264，BICUBIC、4096视觉token上限；实际提示4044token（16文字＋4028图像）、4批。内部最终像素尺寸未提供，不能以源PNG尺寸或模型336元数据声称内部不缩放。未人为裁切或降低输入质量。

Xeon E3-1270 v5，4物理／8逻辑核，AVX2；测试前MemAvailable约24.1GiB、负载0.29/0.24/0.15、磁盘余量278GiB。隔离容器2CPU、16GiB，memory-swap总16GiB，cgroup swap.max=0，network none、只读根、非root、输入只读，仅私有缓存/结果可写。实际 n_threads=2 / n_threads_batch=2；辅助线程不等于额外计算配额。宿主已有swap未调整，生产Worker4GiB保持。

参数：num_gpu=0、num_thread=2、num_ctx=8192、num_predict=4096、temperature=0；统一原图转写指令，无历史OCR、参考文字或M3输入。单页1800秒上限；诊断重试采用剩余1190秒预算，没有自动扩时。

## 失败、诊断与时间口径

| 尝试 | 结果 | 时间与资源 |
|---|---|---|
| 12页基线 | FAILED：prediction aborted, token repeat limit reached；1365字符部分输出 | 请求605.233秒；页面605.368秒；含清理605.633秒。cgroup CPU1210.199核秒，平均1.998核；cgroup峰值5,164,376,064字节（4.81GiB）；进程采样HWM3,464,592KiB；swap/OOM均0，容器exit1 |
| 12页诊断字符串stop | ABORTED_INEFFECTIVE_STRING_STOP；尚无返回文字，停止时仍在视觉编码阶段 | 容器367.049秒；最后采样356.214秒，CPU710.467核秒、峰值3,530,285,056字节（采样时点值），swap/OOM0。受控stop超10秒后exit137、OOMKilled=false，不属于OOM |
| 23页 | NOT_RUN_FIRST_PAGE_NOT_COMPLETED | 时间、内存、文字质量不可评估 |

原生错误响应不含成功的eval_count/load_duration等字段，token完整用量不可得。兼容转换、加载及提示阶段嵌套，不能相加。四个图像提示批的语言解码计时合计46.721秒属于嵌套提示处理，不能冒称独立视觉编码时间。首次token时间、独立布局/视觉/导出耗时未测出；无布局模型。失败耗时不当成功识别速度。

定位证据：实际GGUF与[官方生成配置](https://huggingface.co/zai-org/GLM-OCR/blob/2e85a62840ccac27daa451df36c736c4636b8628/generation_config.json)对应结束ID59246 `<|endoftext|>` 和59253 `<|user|>`，但运行日志只注册59246为EOG。Ollama0.40.1的 llm/llama_server.go 重复守卫比较去空白后的流式文本，连续重复超过100次报上述错误。API未暴露实际隐藏重复token序列，不能声称直接观测了59253重复100次。

[上游issue18609](https://github.com/ollama/ollama/issues/18609)及[尚未合并的PR17195](https://github.com/ollama/ollama/pull/17195)记录相同GLM-OCR EOT问题。诊断时曾添加官方支持的字符串stop，但这匹配解码文本，不能修复被过滤的控制token；发现该证据后停止重试。重试还复用了官方迁移缓存，并非严格单变量对照；未再次复现终态错误，不把中止写成第二次同样失败。未修改权重、禁用重复守卫或采用未发布补丁。已确认兼容性阻塞，未证明所有潜在原因均定位。

## 原图局部对照与阶段结论

开发侧查看两张源图及已保存放大裁片，未冒称用户人工认证或整页逐字参考。12页部分输出的“乌梁素海”“就湖治湖”“预想的结果”与原图一致；仍有“生态督务”误读（源图为“生态警务”）、页顶标题及印刷页码缺失、侧栏移至末尾。可见题干/选项分段较好，但不能将6个题号候选/24个选项前缀或1365字符当整页成功证明。23页没有GLM输出；源图局部字形严重受损，125与127之间题号不能凭顺序猜改为126。无可靠全页逐字参考，不报整页准确率。

| 方法／实际路线 | 两页实测状态与时间（12／23） | 文字与组织、成本及映射 | 阶段判断 |
|---|---|---|---|
| MinerU4.0.10 Basic，ONNX传统OCR | 均完成，9.672／4.385秒（后页温运行） | CPU快，困难字形和题干选项粘连明显；原生归一化坐标可留存，未逐块验证映射 | 适合作为快速基线，用户认为组织明显弱于M3；不扩大50页 |
| MinerU4.0.10 Standard，MinerU2.5-Pro-2605-1.2B Q8_0＋PP-DocLayoutV2，llama.cpp CPU | 均完成，346.878／289.061秒 | 约2.36／2.31GiB进程峰值，近2核；组织优于Basic，仍有乌梁“索”海及困难页关键误读；原生归一化坐标对应包装PDF，未全面验证 | 当前已成功的本地CPU候选中可继续保留，质量优越性未证明，不自动优化/扩页 |
| PaddleOCR-VL1.6原生Paddle CPU＋PP-DocLayoutV3 | 均完成，1015.088／713.368秒 | 约9GiB进程峰值、接近1核；“就湖泊湖”误读；提供原生区域坐标 | 当前CPU成本高，未证明更高忠实性，暂停扩大 |
| MonkeyOCRv2-B-Parsing Torch CPU float32 | 12完成439.681秒；23在746.296秒主动中止过量生成 | 12约6.49GiB；三个指定短语一致。23仅部分调用无完整原生MD/JSON，末尾小区域生成异常；部分坐标保留，不编造缺失映射 | 完整页稳定性不足，暂停 |
| GLM-OCR Q8_0 Ollama0.40.1 CPU整图 | 12失败605.368秒；23未运行 | 4.81GiB容器峰值、约2核，部分文字有收益亦有错误；无布局或坐标；结束标记兼容阻塞 | 不作为当前可用整页后端，不继续环境试探 |
| 历史MiniMax-M3直接原PNG远程 | 均有历史响应，10.338／12.417秒；本轮新调用0 | 组织较好，45D“预期”与源“预想”不符；无原生坐标，服务内部缩放未知 | 保留质量对照；远程速度不与本地CPU当同硬件排名，不宣称逐字正确 |

其余候选均严格复用历史产物，固定身份、内部裁切及失败细节见各自报告：MINERU_STANDARD_TWO_PAGE_REPORT.md、PADDLEOCR_VL16_TWO_PAGE_REPORT.md、MONKEY_CPU_TWO_PAGE_REPORT.md、OCR_BACKEND_COMPARISON10_REPORT.md。表中资源口径不同已明确，不能将进程RSS小于4GiB等同适配生产Worker、60秒受限执行或正式接入。

阶段建议：停止扩展候选，先由用户在同原图上比较现有结果。M3是已具可读组织的历史基线，MinerU Standard保留本地候选；没有证据宣布某路线为整册最准确。GLM当前固定官方CPU组合因终止兼容性未通过整页，不建议直接使用；本轮不转测其他引擎/模型、不部署或生成正式题册。

## 交付与验证边界

私有证据根：`runtime/paddleocr-vl-evaluation/glm-ocr-two-pages-r1`（外层项目）。`trials/page-12-attempt-1`保留原始NDJSON、错误响应、部分转写和资源日志；attempt-2-aborted保留主动停止及状态。`results/glm-ocr`为有状态的展示适配，原始文字不纠错；23仅未运行回执。`research/post-run-model-hashes.json`保留缓存复核，模型/原图/完整响应不入Git。

六路离线包包含两张原PNG、历史原生结果、GLM部分原文及两次尝试记录、content.md/structure.json和本报告。GLM无坐标标null，不生成虚假原生Markdown/JSON。交付副本仅去掉实验自动生成的临时公钥日志行并留原文件SHA，私有原日志不变。不存在业务凭据或模型权重。确切共享位置、大小、SHA见 `evidence/glm-ocr-delivery.json`。

真实验证：模型/输入/镜像身份、离线受限容器失败与资源证据、源图局部看图、六路 file:// 浏览器展示。32项合成回归通过；Ruff、shell语法及diff检查通过。浏览器检查是原图尺寸、文字DOM字节一致、状态、无外网请求/JS错误等机制验证，不是识别准确率。未知项：GLM完整页输出及23页质量、内部实际视觉像素尺寸、隐藏结束token轨迹、用户客户端实际下载和全文核对。没有人工审核状态系统、评分、RAG或自动路由。
