# 十页CPU横向实验入口（仅开发）

## GLM-OCR官方Ollama CPU两页增量

**当前固定组合未通过完整调用终态。** 第12页原生重复保护报错，有原始部分文字；唯一字符串stop诊断被主动停止，第23页未运行。此入口用于可追溯复现，不能写成可用生产能力。官方配置EOS [59246,59253]与本次原生EOG仅59246存在差异；`--diagnostic-stop-strings`只是保存的诊断开关，不能注册原生EOG，不能作为修复方案。原因及边界见[GLM两页报告](GLM_OCR_TWO_PAGE_REPORT.md)。本轮不继续改权重/编译未合并补丁/回退旧引擎。

独立入口为`run_glm_ocr_cpu.py`及`launch_glm_ocr_cpu.sh`，不接入生产FileTools。只做整页识别模型，不声称运行SDK的PP-DocLayout-V3布局＋区域识别。官方Ollama原生`/api/generate`接口在**同一断网容器的loopback**上使用；`OLLAMA_NO_CLOUD=1`、不提供API key、不暴露端口。请求只含实际PNG字节base64及官方`Text Recognition:`任务提示，不提供历史OCR或参考。客户端解码后的SHA/尺寸单独记录；内部视觉缩放另见运行日志，不能以base64证明内部不缩放。

先按本轮报告固定官方Ollama发行资产、完整官方SHA、模型分发manifest及全部blob SHA。`inspect_gguf_metadata.py`仅读取公开权重元数据/张量计数，不加载模型，不输出tokenizer词表。准备阶段可下载官方文件，推理阶段不可下载。`deploy/Dockerfile.glm-ocr-cpu`使用既有非生产Python研究镜像及私有build/engine中的官方CPU文件，不向宿主或Gateway/Worker安装。重建前核对基础镜像完整ID，并记录最终实际镜像ID；tag不代替校验。GPU目录不提取，上游二进制/安装包不打补丁。官方运行时可能生成兼容转换缓存，仅允许写入独立实验models，保留原始blob/manifest副本、转换后清单和各自哈希。

使用显式manifest中的单页输入；脚本核对图片SHA，拒绝已有输出目录，避免无声覆盖或断联重跑。`bash scripts/launch_glm_ocr_cpu.sh <独立实验目录> <已核实镜像完整ID> 12`启动detached容器，随后读取持久receipt/资源及docker终态。第23页须等第12页SUCCEEDED才显式启动。launcher检查实际MemAvailable，而非宿主总内存；此外仍须人工检查服务负载。容器2CPU/16GiB、memory-swap总16GiB、network none、只读根/源码/输入、nonroot、cap-drop/no-new-privileges，1800秒整次硬上限。源图片与模型/历史产物不位于生产cache，不能冒充正式发布附件。

逐响应块保存response.raw.jsonl及原样partial文字；完整stop、空输出、长度终止、无终态、异常和超时分别记载。HTTP错误正文/堆栈保留，不从超时推断质量差；1800秒硬截止的timeout.json与Docker退出状态、部分文件共同判定。退出码0/stop仅代表调用结束，不代表整页无遗漏。进程采样RSS、子进程getrusage、cgroup memory.peak/CPU/swap口径分别保留，不能相加；独立视觉编码/布局耗时不提供时写未知，prompt_eval不是自动等同视觉编码。

原生API JSON/流不覆盖，raw.md为响应文本原样存储；blocks.json/content.md/structure.json属于明确标识的最小格式适配，一个未分段文字块、坐标null、无布局模型。复用现有bundle生成离线对照，不改写文字或声称题目结构已核实。历史候选仅复制并标明复用，不发起M3请求。私有原件、完整响应、模型、图片、带正文日志不提交；Git仅保留通用代码/合成测试/白名单脱敏指标及报告。

结果与限制见[报告](OCR_BACKEND_COMPARISON10_REPORT.md)。不自动选择后端、不改生产Skill；保留已安装试题模板。所有私有工作目录应在忽略的runtime下。模型准备允许联网，推理不联网；脚本没有云推理客户端。

## 环境与准备

`deploy/Dockerfile.ocr-backend-comparison`有paddle、mineru、monkey三个target。核对注释中的本地基镜像ID；Python基镜像digest固定。当前实际结果用报告列出的三个镜像ID。`deploy/ocr-comparison-locks/*.txt`是该次实装快照；未来重建后必须比较freeze，不能仅凭tag声称复现。准备镜像的下载镜像与官方来源SHA审计分别记录，不改生产镜像。

`prepare_ocr_comparison_assets.py models <固定官方HF metadata.json> <模型目录>`验证固定revision、文件大小及LFS SHA/Git blob。`--official-mirror`仅对LFS模型权重启用官方README链接的镜像，代码与配置仍取固定HF。命令只处理公开模型，不收业务图片。`monkey-code`从固定GitHubrevision读取CPU入口及预处理源码。metadata、下载日志、固定manifest必须随实验保留。

每次前检查实际可用内存、磁盘和服务负载；宿主总内存不是Worker额度。不要传GPU、生产配置、凭据、Docker socket或业务目录写权限。依次启动一个候选，pilot成功后才运行剩余页。

## MinerU实际成功路线示例

下述EXP_DIR需指向**已经准备好**的独立实验目录，REPO_DIR为测评工作树。不存在时停止，不扫描NAS寻找替代。模型根含`MinerU-4_models_onnx`子目录，配置使用仓库`deploy/ocr-comparison-mineru.yaml`。先指定12页，查看终态和非空原生输出，再单独目录指定其余页。

```bash
# 在调用前显式设置并检查EXP_DIR、REPO_DIR，参数不得指向生产目录。
docker run -d --name filetools-ocr-compare-mineru-new-pilot \
  --network none --read-only --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --cpus 2 --memory 16g --memory-swap 16g \
  --pids-limit 128 --tmpfs /tmp:rw,size=2g \
  --tmpfs /models/.locks:rw,size=1m,uid=1000,gid=1000 \
  -e HOME=/tmp -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 -e OPENBLAS_NUM_THREADS=2 \
  -e MINERU_INTRA_OP_NUM_THREADS=2 -e MINERU_INTER_OP_NUM_THREADS=1 \
  -e MINERU_HOME=/tmp/mineru -e MINERU_TABLE_DEVICE=cpu \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e MINERU_CONFIG=/config.yaml \
  -v "$REPO_DIR:/repo:ro" -v "$EXP_DIR/images:/images:ro" \
  -v "$EXP_DIR/models:/models:ro" -v "$EXP_DIR/results/mineru/new-pilot:/results:rw" \
  -v "$REPO_DIR/deploy/ocr-comparison-mineru.yaml:/config.yaml:ro" \
  filetools-ocr-compare:mineru4010 \
  /repo/scripts/run_ocr_backend_comparison.py --backend mineru \
  --images /images --models /models --output /results --pages 12 \
  --load-timeout 180 --page-timeout 300
```

配置环境变量MINERU_CONFIG已对照官方实现核实；上例不是生产FileTools工具或沙箱正式交付。断开终端后Docker继续运行，结果落盘；终态看`run-receipt.json`、每页`page-receipt.json`及stderr，不用container退出0代替内容验收。续跑显式`--resume`保留既有尝试，成功页只有SHA相同才跳过。图像同名但哈希不同会拒绝。

Paddle调用`--backend paddle --models <已有固定VL1.5模型根>`并保留原CPU YAML；Monkey调用`--backend monkey --models <固定模型目录> --source <固定CPU源码根>`，HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE打开。使用各自实际镜像与入口；加载180秒、每页300秒及全部容器资源/断网设置相同。本轮两者pilot超时，未进入十页，不把换引擎或加核后的结果混合。

## 原样适配与界面

`ocr_backend_comparison.py adapt-mineru --folder ... --page N`保留原生树，将官方structured export的顺序及normalized bbox映射为最小块。每页原文不改；默认Markdown和full-mode Markdown分开。`import-m3 --experiment ... --manifest ... --output ...`仅复制历史匹配源PDF/图像SHA及原响应相等的文本，不发请求。

`bundle --manifest ... --candidate mineru=... --candidate m3-history=... --candidate paddle=... --candidate monkey=... --output <新目录>`生成各方法content.md/structure.json及无网络file:// HTML。输出目录已存在则拒绝。无坐标、未运行、失败、超时分别明确记录。原始输出不得用生成器或模型整理替换。

`browser_smoke_ocr_comparison.py`依赖开发Playwright，逐页验证图像尺寸、原始文字DOM字节一致、无外部请求、无水平溢出；可选`--font`仅注入开发截图字体，不改变交付。该工具不评价识别正确性。

合成测试覆盖原文/坐标保留、页重置告警、历史来源校验、安全HTML、非文字/页眉块、并发捕获、续跑保留、shape观察。不得把这些测试称真实模型识别通过。私有资料只放runtime/共享交付，Git只收代码、配置、脱敏测量和报告。

## VL1.6整页有界实验（2026-10-08增量）

实测见[PaddleOCR-VL1.6两页报告](PADDLEOCR_VL16_TWO_PAGE_REPORT.md)。沿用paddle370镜像的软件包，另行下载并校验真实1.6权重；不能把1.5模型目录直接改名。模型根必须含固定`vl`、`layout`；VL的verified-assets.json记录官方版本校验，既有布局文件的实际哈希另存layout-assets-used.json。当前输入为同一220dpi PNG，先12页完成后才启动23页。下例只运行显式一页；下一页另建结果目录、核对实际空闲资源再启动。

```bash
# EXP_DIR/REPO_DIR须指向已准备并校验的隔离实验目录，不挂生产配置或凭据。
docker run -d --name filetools-vl16-new-page12 \
  --network none --read-only --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --cpus 2 --memory 16g --memory-swap 16g \
  --pids-limit 128 --tmpfs /tmp:rw,size=2g \
  -e HOME=/tmp -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 -e OPENBLAS_NUM_THREADS=2 \
  -e FLAGS_paddle_num_threads=2 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -v "$REPO_DIR:/repo:ro" -v "$EXP_DIR/images:/images:ro" \
  -v "$EXP_DIR/models:/models:ro" -v "$EXP_DIR/results/new-page12:/results:rw" \
  sha256:cb90de65a52f53707a05e26e0e8cfb09622e9001adde93f0359f15eaf8e23f56 \
  /repo/scripts/run_ocr_backend_comparison.py --backend paddle --paddle-version 1.6 \
  --cpu-threads 2 --instrument-paddle --images /images --models /models \
  --output /results --pages 12 --load-timeout 180 --page-timeout 1800
```

线程flag由实际get_flags确认，CPU用量仍需监测，不能从参数推出两核满载。`phase-events.jsonl`、`activity.json`、`resource-samples.jsonl`记录布局、区域裁切、模型tensor形状、视觉及生成嵌套阶段；这些是研究观察器，不改安装包源码/识别结果，也不构成生产能力。`raw-regions`保留原生区域响应（含数组），`raw-generations`保存生成token；部分区域不能当整页。

只有原生整页导出完成才用`ocr_backend_comparison.py adapt-paddle --folder <原生单页目录> --page 12`。它保留原生MD字节和坐标。历史M3仍通过`import-m3`复用，无新云请求。`summarize_paddle_vl_trial.py --folder <尝试目录> --output <脱敏摘要.json>`仅汇总已记录测量，不补未知时间或推定准确率。

## MonkeyOCRv2两页CPU有界实验（2026-10-08增量）

[两页报告](MONKEY_CPU_TWO_PAGE_REPORT.md)保留原300秒pilot，新的单页目录最多1800秒；12完整原生输出后才启动23，不自动扩页。复用已校验的Monkey模型目录与固定官方源码目录；不是正式FileTools工具，不绕过生产沙箱交付。

```bash
# REPO_DIR/EXP_DIR/MONKEY_MODEL_DIR/MONKEY_SOURCE_DIR需指向已核对的独立开发资源。
docker run -d --name filetools-monkey-new-page12 \
  --network none --read-only --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --cpus 2 --memory 16g --memory-swap 16g \
  --pids-limit 128 --tmpfs /tmp:rw,size=2g \
  -e HOME=/tmp -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 -e OPENBLAS_NUM_THREADS=2 \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -v "$REPO_DIR:/repo:ro" -v "$EXP_DIR/images:/images:ro" \
  -v "$MONKEY_MODEL_DIR:/models:ro" -v "$MONKEY_SOURCE_DIR:/source:ro" \
  -v "$EXP_DIR/results/new-page12:/results:rw" \
  sha256:4e1dab1610ca1cfccb77809e72c9fa70122c0b859d9f2d4ec6281c339595b599 \
  /repo/scripts/run_ocr_backend_comparison.py --backend monkey \
  --images /images --models /models --source /source --output /results --pages 12 \
  --load-timeout 180 --page-timeout 1800 --instrument-monkey --monkey-max-inflight 1
```

`--monkey-max-inflight`默认1024保留旧基线，新的CPU实验显式用官方参数1，避免32个区域worker争抢2CPU；观察器本身不锁模型计算。Torch实际intra-op2/inter-op1在metrics记录。`--instrument-monkey`代替旧双重prepare捕获，记录实际load_image返回一次，不改模型输入/提示词/采样参数，原生文字与token另存。进度、日志、每次完整区域结果即时落盘；续跑仍须显式--resume，不覆盖成功页。

只对有完整原生jsons/markdowns的成功页使用`ocr_backend_comparison.py adapt-monkey --folder <原生页目录> --page 12`。同目录保存blocks.json/raw.md；原生markdowns与images相对路径保留。raw.md是原生MD逐字节副本，图片相对路径仍以原生markdowns位置解释，不静默改写。bbox坐标属于官方warp后的页，未提供逆映射则不假称原图坐标。原生导出的strip/标题格式及替换符过滤属于工具行为，原始逐调用文字仍保留，不用原生MD冒充无格式处理的模型响应。

复用原bundle入口组合monkey/paddle-vl16/m3-history（MinerU可选）；不重新请求M3。现有`summarize_paddle_vl_trial.py`扩展白名单兼容Monkey阶段，仅输出不带query/raw_text的测量。合成测试检查观察器输入/返回值恒等、并发不被日志锁串行化、ID隔离、脱敏白名单及预处理坐标系；不代表OCR准确或生产能力通过。

## MinerU Standard本地CPU两页（2026-10-08）

沿用同一MinerU4.0.10镜像与ONNX小模型，新增官方registry指定的`jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`，revision `9185688a0495e1577d521a757c7c0b62dd38ca48`，主模型与mmproj的Q8_0文件；详见`docs/evidence/mineru-standard-fixed.json`。不是Basic改名，不是远程HTTP客户端，也不是Paddle/Monkey权重复用。

准备阶段允许网络：既有流式下载脚本逐文件验证固定HF元数据；再由官方ModelRepo.ensure下载/验证快照并生成完成标记，不手造`.mineru_complete`。官方snapshot_download在本次准备中显式固定revision；完成后再次核对两个大文件SHA。模型站访问使用既有开发网络设置，禁止记录代理值/密钥；推理不继承任何代理、认证或服务端点。

沿用上面的隔离docker run，修改且仅修改实验参数：

- 模型根含`MinerU2.5-Pro-2605-1.2B-GGUF`；既有`MinerU-4_models_onnx`作为其子目录只读挂载（可复用历史模型根，不复制或下载小模型）。模型锁仍独立tmpfs。
- 只读挂载`deploy/ocr-comparison-mineru-standard.yaml`到`/config.yaml`；本地engine=llama-cpp，server_url为空，source=local，max_concurrency=1，LLM辅助关闭。
- 入口增加`--mineru-tier standard --cpu-threads 2 --observe-shapes --page-timeout 1800`；仍2CPU、16g memory和memory-swap，network none、nonroot、只读根、安全限制不变。
- 先`--pages 12`，确认原生完整终态后再用独立`trials/page-23`目录运行`--pages 23`。使用detached Docker；失败尝试保留，`--resume`归档旧日志、终态及未完成页；成功SHA相同才跳过。新版本归档后移走旧终态回执，避免后台运行期间误读上一轮失败为当前结果。

`mineru_standard_observer.py`仅在研究进程包装官方Engine，显式传其支持的`n_threads=2,n_gpu_layers=0,n_parallel=1,verbosity=3`。安装版配置没有这些Engine字段，因此不伪造YAML参数；不修改安装包文件或换识别管线。记录真实prepare_for_extract输入布局/内部页尺寸、Engine实际data-URI图像字节、原始messages/采样参数/GenerateResult/token/引擎timings，业务内容仅留私有目录。原函数入参/返回不改，不调用第二次prepare或生成。首次将Helper方法错误定位到Client的初始化失败保留，最终使用真实`MinerUClientHelper`，通过合成回归及真实调用。

`standard-phases.jsonl`记录VLM加载、含布局/渲染/ONNX加载的window_prepare、包含视觉与生成的各次Engine.generate、原生save导出；不能将嵌套计时相加，prompt_ms不等于独立视觉编码耗时。未提供的算子耗时/内部视觉张量缩放写未知。`summarize_mineru_standard_trial.py --folder <trial> --output <sanitized.json>`只输出测量白名单，不输出原请求/正文；合成测试覆盖脱敏。

成功后沿用`adapt-mineru`、`bundle`和实际浏览器检查。默认MD可能过滤页边文字，`full-mode.md`和原生JSON独立保留；原始逐区域响应才是视觉模型原文，不以格式适配后的Markdown替代。不得将JSON字段齐全/程序零异常当逐字正确或题目结构验收。
