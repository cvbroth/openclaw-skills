# 十页CPU横向实验入口（仅开发）

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
