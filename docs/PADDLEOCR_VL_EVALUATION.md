# PaddleOCR-VL 与 PP-StructureV3 独立三页评估

本评估与整册文档开发隔离。原分支868c25dc及其未提交结构/模板/Skill成果保留，不把评估镜像用作生产Worker，不改变RapidOCR、Gateway、挂载或限额。不重新识别整册，不上传原页到外部服务，不永久保存或导入知识库。

## 范围与固定环境

仅指定原PDF物理第6、10、30页，220dpi原页图直接输入。第30页来自现有预检首个多选题候选页；实际看图确认该页包含单选末段与多选开始、题号重置及同行选项。原OCR只用于识别完成后的对比，不挂进推理容器；原始产物不改写。

采用[官方CPU部署路线](https://www.paddleocr.ai/v3.4.1/en/version3.x/pipeline_usage/PaddleOCR-VL.html)：Python3.12、PaddleOCR3.4.0、PaddleX3.4.0、PaddlePaddle CPU3.2.2。本机显卡GeForce210使用nouveau，无nvidia-smi/CUDA设备；显存数值未取得，不把PCI内存窗口当可用显存。Xeon E3-1270v5有AVX2，4核8线程；核对时主机31023MiB总内存、19088MiB available，开发盘312GiB余量。生产Worker仍为4GiB；本独立测试容器选择8GiB、2CPU，不改变生产额度。服务负载/内存是时点记录。

固定官方模型：

- PaddlePaddle/PaddleOCR-VL-1.5，提交2a4195faa5e7914c12f2fc601d72c81caf8d2da5；权重1917255968字节、SHA256 d557c9d8997ae57ed3b1b33bdf347be878cc335687f32ca105341c16973f8958。
- PaddlePaddle/PP-DocLayoutV3，提交241f8bdfc77a7c7bee915a5057aaee58c235a8d3；权重130806572字节。

模型权重约2.05GB；连同Python依赖预计下载3–4GB，镜像与独立缓存预留12GB，不拉官方GPU大镜像。准备阶段联网下载官方模型及依赖，处理阶段network:none。所有模型文件最终记录实际字节/SHA，完整依赖freeze与镜像ID在非私密证据；准备失败时不称固定环境已建成。官方备用下载源仅在校验同一固定权重SHA后采用，不使用收费识别服务。

`deploy/paddleocr-vl-cpu-eval.yaml`来自固定PaddleX包配置，页/布局/VLM批量均1、关闭异步队列。Markdown不排除number/header/footer等标签，防止对比时把被过滤的文字误当模型漏识。仍保留完整原生JSON，不只比Markdown。orientation/unwarping关闭；原页无人工裁正或OCR提示。

## 有界执行与复现

`deploy/Dockerfile.paddleocr-vl-eval`只构建独立开发镜像，复制既有开发虚拟环境后增量安装，原环境不改。`deploy/paddleocr-vl-eval.requirements.lock`来自实际镜像freeze（排除基础镜像自带项目本体的本地安装路径，将Paddle官方本地wheel记录为3.2.2）；Dockerfile使用此约束锁。准备脚本只下载两个固定官方仓库，不读业务目录。没有生产Compose改动。

实测基础镜像ID为`sha256:f00d08c74004014b9cc098cd2f705befae75ee945c6698b77e42e5bca7cb9f68`；重建前用`docker image inspect filetools-document-compat:20261006-pdfium513 --format '{{.Id}}'`核对，标签指向不同ID时停止。独立构建上下文只放下列两个文件，不放原页或OCR：

- 从[官方CPU索引](https://www.paddlepaddle.org.cn/packages/stable/cpu/paddlepaddle/)下载`paddlepaddle-3.2.2-cp312-cp312-linux_x86_64.whl`。实测官方URL为`https://paddle-whl.cdn.bcebos.com/stable/cpu/paddlepaddle/paddlepaddle-3.2.2-cp312-cp312-linux_x86_64.whl`，189280697字节，SHA256 `f6b3b73d47acc82cf545896e6e5c31b55a7f9a26dc0acb28abcc24069d9396dd`；Dockerfile先验哈希。
- 复制本仓库`deploy/paddleocr-vl-eval.requirements.lock`到上下文根目录同名文件，再使用本Dockerfile构建专用评估标签。

模型准备入口：`python3 scripts/prepare_paddleocr_vl_models.py --models <独立模型目录> --metadata <独立元数据目录>`。脚本获取指定提交元数据，核对小文件Git blob及权重LFS SHA/大小，输出manifest。HuggingFace传输失败或缓慢时，可明确加`--official-weight-mirror`，仅权重改用官方README链接的ModelScope；即使其URL使用master，也必须匹配固定HuggingFace提交的SHA，配置仍用固定提交，不随master更新。下载发生在准备阶段；推理阶段继续断网。

锁文件和校验步骤是在实测镜像freeze后补入重建配方，修订后的Dockerfile尚未重新构建；不能把配方审核等同于另一镜像已经验收。实际测试始终使用下述确切镜像ID。

示例路径变量须换成已授权独立开发目录，不把生产目录整个挂入测试容器：

```bash
docker run --rm --network none --read-only --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 8g --memory-swap 8g --pids-limit 96 \
  --tmpfs /tmp:rw,size=2g \
  -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 -e OPENBLAS_NUM_THREADS=2 \
  -e PADDLE_PDX_CACHE_HOME=/tmp/paddlex -e HF_HOME=/tmp/huggingface \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -v "$evaluation_repo:/eval:ro" -v "$evaluation_images:/images:ro" \
  -v "$evaluation_models:/models:ro" -v "$evaluation_results:/results:rw" \
  filetools-paddleocr-vl-eval:cpu-3.4.0-paddle3.2.2 \
  -B /eval/scripts/evaluate_paddleocr_vl.py --images /images --models /models --output /results
```

加载上限180秒、每页上限300秒，总监控有界；超时终止该独立测试进程组并保留阶段/日志，不扩大额度。原生预测一次初始化再顺序处理三页，区分包导入、模型加载、首推理和后续推理。峰值RSS包含该进程库/模型，后续页面RSS为累积高水位，不能冒称单页独占峰值。无GPU时显存指标不适用。超时/失败不填虚构CER或识别时间，更不按三页外推整册。

## 对比方法与验收边界

实际看原页建立独立选段参考，再读取旧RapidOCR和新模型输出，分别标出已知漏行、题号、题干、否定词、数字、A–D、同行选项与顺序。选段CER仅移除空白，大小写、标点、圈号等仍计入；明确参考范围、参考图SHA、review_method与用户二次人工核验状态。Agent实际看图逐字转录不冒充人类用户已逐字复核。`score_ocr_blocks.py`输出选段距离/字符数/CER；无成功识别则标不可计算，不用0填补。整题/选项完整性另列，不以模型置信度或榜单代替。

原PDF既有印刷页码跳转沿用前轮原页核实证据独立记录，原因未知；本次三页不能验证全书缺页或总体OCR准确率。原页、OCR正文、模型缓存、带正文日志与选段参考只留ignored runtime，不提交GitHub。仅推脚本、固定环境说明及去正文报告。

## 实测结果

执行日期：2026-10-06准备，2026-10-07有界CPU试验。结论：**共享模型加载在8GiB上限内失败，三页识别对比未完成**。不把脚本测试、权重下载或原页看图称为模型识别成功。

实际镜像`filetools-paddleocr-vl-eval:cpu-3.4.0-paddle3.2.2`，ID `sha256:2b423d1a39d0a064e35fdef74f88bf2b34837b9eba8b36d85329bf18941f3cb3`，虚拟大小1556082193字节。实际Python3.12.10、PaddlePaddle3.2.2/PaddleOCR3.4.0/PaddleX3.4.0、NumPy2.5.3，cv2实际导入4.10.0。完整固定版本见锁文件。

| 实测项目 | 结果 |
|---|---|
| 包导入 | 复验3.883642秒 |
| 模型加载完成耗时 | 不可取得；未加载完成 |
| 至失败总耗时 | 34.501660秒（含包导入） |
| 失败阶段 | 本地权重设置到模型期间，Docker `OOMKilled=true` |
| 子进程/容器退出 | 子进程-9；监控容器2 |
| 进程峰值RSS | 8369148KiB，约7.98GiB |
| 容器内存峰值 | 8589934592字节，达到8GiB硬上限；包含进程及缓存，与RSS口径不同 |
| 加载/单页时限 | 180/300秒，未因超时结束，不扩容或延时 |
| 第6、10、30页识别时间 | 均未进入识别，不填0秒 |
| 完成页/新模型CER | 0页；CER不可计算 |
| 后续热推理/GPU峰值 | 未进行/无可用CUDA设备 |

首次尝试同样记录OOM，但监控读取已退出进程的无VmRSS/VmHWM状态时触发TypeError，回执未落盘，不能虚构其峰值；已保留原日志并修复。第二次以完全相同模型/镜像/限额复验一次，获得上述完整失败证据。没有为每页重复三次相同加载故障，也没有自动增大资源。两次均为新进程加载尝试，第二次可能复用系统磁盘页缓存，不能称为成功后的热推理。

依赖`pip check`通过；requests报告版本兼容警告。环境含opencv-python4.11.0.86与opencv-contrib-python4.10.0.84两个发行包，实际cv2导入4.10.0；pip check不验证共享二进制文件兼容性。未认定这些警告或包重叠是OOM原因。成功加载和识别前，不能称依赖已通过完整运行验收。

**真实原页/旧OCR对比**：已实际查看3张220dpi原图。第6页第4题漏行、第10页第32题题号和开头丢失存在于旧OCR，原图对应文字可见；第30页多选第5题某选项缺1字，第1题有标点差异。比较只记录现象，不改原OCR，不凭学科知识纠错。新模型没有输出，无法判断哪些被恢复或新增误读、否定词/数字准确率及阅读顺序收益。

| 看图选定块 | 非空白参考字符 | 旧RapidOCR编辑距离 | 选段CER | PaddleOCR-VL |
|---|---:|---:|---:|---|
| 第6页第4题题干 | 111 | 43 | 38.74% | 未识别 |
| 第10页第32题题干 | 174 | 45 | 25.86% | 未识别 |
| 第30页多选第1题及选项 | 139 | 1 | 0.72% | 未识别 |
| 第30页多选第5题及选项 | 93 | 1 | 1.08% | 未识别 |

共517字符，90处编辑差异，合并选段CER17.41%。这是刻意针对已知疑点选段的、**Agent看图逐字转录参考**的暂定度量；用户二次人工逐字核验未完成，不称人类认证基准，不代表整页或整册。用户尚未逐字核验参考文本，因此不能将上述结果称为用户人工核验CER。去正文计分证据保留参考哈希、图像哈希、核验方法和范围。

整题/选项完整性另记：原图第6页5道完整题/20选项；第10页5道完整题，另含上页第27题延续选项，合计24选项；第30页3道单选末题与5道多选，共32选项。上述是查看原图的预期结构，**不是新模型通过的题目/选项计数**。旧OCR两处题干缺失仍在，新模型完整性未评定。3页没有材料题/图片/表格覆盖。

原PDF页码跳转独立保留：既有原页核对记录为物理64→65页印刷59→65、112→113页印刷112→117、149→150页印刷153→157。本轮未重新读取这几页；原因未明，不把它们归为本次OCR漏页，也不声称确认全书缺页。

准备成本：18个模型文件实际2062328724字节，均完成固定版本校验；独立目录实占约2.6GiB（包含官方wheel、模型及失败下载partial等），镜像虚拟约1.56GB，层可能与基础镜像共享，不能直接求和当唯一磁盘占用。初估3–4GB下载、12GB磁盘预留充足；重试流量未计量，不能将留存文件字节当实际网络流量。HuggingFace HTTP/2失败及缓慢传输后，采用官方README链接的备用源并匹配同一权重SHA。构建日志依赖安装步骤8223.8秒，属准备成本，不能当加载/推理耗时。没有使用付费或远端识别服务。

**建议**：当前本机2CPU/8GiB CPU方案不适合继续识别，优先考虑兼容GPU或自托管远端的独立评估。本轮未完成准确率对比，不能认定比RapidOCR更好或收益不足。8GiB是主动设置的测试上限，并非宿主机物理极限；不能据此断言本机CPU绝对跑不了。若继续更高内存CPU尝试，需先确认新的资源边界和服务负载，本轮不自动扩大。未测出足够加载内存的具体值，只能证明此次8GiB不足。

真实验证：硬件/当前负载、3张原图及旧OCR选段、官方文件校验、VL两种资源额度的加载/运行结果、PP离线初始化失败及进程/容器峰值。自动验证：非OCR仓库套件142 passed、15 skipped；更新后聚焦的OCR watchdog/PP配置/CER计分测试5 passed；变更脚本及测试的Ruff检查通过。首次全套检查在错误的2GiB容器tmpfs下有10项因项目DISK_RESERVE失败，随后将容器/tmp绑定到开发宿主临时目录后全套通过；未提高生产或OCR容器限制。未验证：两种新方案成功识别、逐页/热推理、人工二次参考核验、GPU性能及识别收益。

整册开发分支及未提交成果保留；本评估独立分支，不替换生产OCR、不修改生产限额/配置、不重启服务。源图、OCR正文和参考转录、日志及模型缓存均不提交；只提交代码、锁文件、无正文报告及计数/哈希证据。

## 2026-10-07 补充：16GiB复测与PP-StructureV3

本节补充并更正上文的8GiB时点结论，不覆盖首次OOM记录。两种引擎按顺序、各自独立容器运行；测试前查看主机可用内存/负载和运行服务。PP启动前记录主机内存可用26222MiB、load average `0.46, 1.20, 0.81`；Gateway健康、FileTools Worker约29MiB，其他运行服务也有采样。每个推理容器设2CPU、16GiB内存且memory-swap同为16GiB（容器不使用swap）、pids 96、`network:none`。GT218无CUDA设备节点，GPU显存不可读取。生产容器、4GiB Worker额度、RapidOCR和配置均未修改。

### PaddleOCR-VL 16GiB复测

沿用原固定镜像`sha256:2b423d1a39d0a064e35fdef74f88bf2b34837b9eba8b36d85329bf18941f3cb3`、模型和配置，仅把容器内存与memory-swap从8GiB同步提高到16GiB。原8GiB OOM证据仍在先前运行记录中。此次离线运行总计43.327秒，包导入2.099秒（进程CPU 2.248秒，约占分配双核能力53.5%），模型加载37.062秒（进程CPU 37.131秒，约50.1%）；进程RSS峰值9,340,936KiB，容器memory peak 9,350,508,544字节。第6页第一次推理运行3.052秒（进程CPU 5.323秒，约占双核能力87.2%）后返回`TypeError: only 0-dimensional arrays can be converted to Python scalars`。进程退出码1，未超时、未OOM。第10、30页没有运行。失败属于运行期类型/兼容性异常；具体根因未定位。

此轮证明模型能在16GiB限额内完成初始化，但未完成页面识别。没有成功输出，三页新模型CER、题目/选项完整性、漏行恢复或新增误读均不可评估；上述失败运行不构成OCR准确率结果。没有成功页面，首张有效推理和后续推理时间均未取得。进程峰值RSS与容器cgroup峰值是不同口径。未取得GPU显存峰值。

### PP-StructureV3独立CPU尝试

采用[官方PP-StructureV3 Python/CPU接口](https://www.paddleocr.ai/v3.4.1/en/version3.x/pipeline_usage/PP-StructureV3.html)，固定Python 3.12.10、PaddleOCR 3.4.0、PaddleX 3.4.0、PaddlePaddle CPU 3.2.2，独立模型锁`deploy/ppstructurev3-models.lock.json`，配置SHA-256 `99ad1bcfc66e0436cbcdccc912f2afab9ca783ff3240ca5b13c07b5ac929b286`。计划启用PP-DocLayout-L版面、PP-OCRv5 server文字检测/识别及其版面顺序结果；表格、公式、印章、图表和区域识别参数设为关闭。这是有意裁剪的文本试题配置，不是完整PP-StructureV3模块集。三个已锁定模型档案分别为130,109,440、88,340,480和84,869,120字节，SHA见模型锁文件。

首次配置尝试实际镜像ID为`sha256:dc202cf886fa3e3d239765f27df55b9b1c4b11885d11f8252dd8a4631860ae93`，离线运行总计85.162秒后在模型加载阶段失败，进程RSS峰值876,324KiB、容器峰值702,722,048字节；没有超时或OOM，没有处理任何页面。实际模型加载阶段耗时未被首次运行指标单独保存，不能用总时长减包导入时间冒充精确加载耗时。错误显示本地`PP-Chart2Table`未挂载时“No model source is available”。对固定安装包源码的独立检查定位到`paddlex/inference/pipelines/layout_parsing/pipeline_v2.py`：即使`use_chart_recognition=False`，初始化仍无条件执行`create_model(ChartRecognition)`；官方内置`PP-StructureV3.yaml`也含ChartRecognition模型配置。因此该选项只关闭后续图表推理分支，未阻止模型预测器初始化。这个实现行为与本次文本-only约束不兼容。上游也有关于该开关仍触发模型下载的[问题记录](https://github.com/PaddlePaddle/PaddleOCR/issues/16552)；本报告依据是固定安装包源码和本次离线错误，而非单凭问题帖推断。

本轮不下载或加载未请求的PP-Chart2Table模型，也不把关闭参数误报为“图表模型未加载”。在这组固定版本下，PP-StructureV3按约束**阻塞于模型初始化**，没有原生JSON/Markdown页面结果。现有预装模块探测和包导入成功不代表管线可运行。评估脚本新增显式兼容性门控，阻止后续运行发生隐式在线模型下载。若未来官方修复可选模型初始化，或另行批准改变模型集/配置，再单独评估；本次不作变更。

### 同口径比较与建议

原图220dpi SHA、看图选段参考和旧RapidOCR结果继续沿用`docs/evidence/paddleocr-vl-block-scores.json`，不重新转录、不把旧OCR作为输入。旧RapidOCR四个选段共517字符、编辑距离合计90，针对已知疑点的暂定CER为17.41%；参考由Agent看图转录，未经用户第二人逐字复核，不代表全页或全册。VL 16GiB复测及PP尝试均无成功识别输出，故对相同517字符均标为**CER不可计算**，不是0，也不能报告比RapidOCR更准确或更差。整题/选项完整性相应为不可评估。

本机当前可用GPU路线不可用。VL在16GiB/2CPU完成模型加载但首张页面失败，CPU运行兼容性仍未解决；PP固定配置被可选图表模型初始化行为阻塞。建议目前先解决VL兼容异常或等待PP官方配置修复，再复用相同三张图测试；现有证据不足以说两者在本机适用，也不足以断言识别收益不足。没有从三页推算整册速度、准确率或内存需求。以上两个失败是本次有效实测；前述8GiB OOM仍是历史实测；PP门控和单元测试属合成/静态验证。

原页、旧OCR正文、独立参考文字、两引擎失败日志和模型缓存均留在ignored runtime，不上传。仅共享评估脚本、锁文件、无正文报告和非私密回执计数/哈希。

## 2026-10-07 后续运行修复与真实识别

最新结果见[独立运行修复报告](OCR_CPU_RUNTIME_REPAIR.md)，保留上文历史失败：原图预处理诊断确认NumPy非零维标量转换错误，独立NumPy2.3.5候选越过TypeError但第6页300秒超时；按新授权提供本地官方Chart2Table辅助模型后，PP-StructureV3在原2CPU/16GiB无swap离线限制下完成全部三页。相同517字符选段参考下，RapidOCR CER17.41%、PP0.39%，VL无完成输出不可评估；这不是整页/整册准确率。生产没有变更。
