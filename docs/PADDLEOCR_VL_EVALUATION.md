# PaddleOCR-VL 独立三页评估

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

真实验证：硬件/当前负载、3张原图及旧OCR选段、官方文件校验、离线加载OOM与进程/容器峰值。合成验证：6项回归覆盖计分、超时终止、退出进程内存字段、版本和文件哈希门控；Ruff通过。未验证：三页新OCR、成功加载耗时、逐页/热推理、人工二次参考核验、GPU性能及准确率收益。

整册开发分支及未提交成果保留；本评估独立分支，不替换生产OCR、不修改生产限额/配置、不重启服务。源图、OCR正文和参考转录、日志及模型缓存均不提交；只提交代码、锁文件、无正文报告及计数/哈希证据。
