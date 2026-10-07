# M3测评中的 `view_image` 来源与图片处理链

排查基线：FileTools测评分支提交 `e0adc0068a88d07990ec1010f0ee8ab135cf520c`。只读检查该提交的提示/传输证据、当次脱敏日志、运行中Gateway镜像打包文件和OpenClaw源码；未读取完整会话、配置文件或凭据，未发模型请求，未运行OCR，未改代码配置或生产服务。

## 结论

`view_image` 是 **OpenClaw核心工具**，不是插件名，也不是Rastermill依赖直接提供的工具。OpenClaw核心 `src/agents/tools/image-tool.ts` 在部署bundle中注册它，`src/agents/tools/image-tool.result.ts` 将图片放入原生图像内容块；Codex扩展另有可用Codex原生图像查看器时的筛选逻辑。图像缩放由OpenClaw核心媒体链执行，底层编码依赖Rastermill。

运行中的Gateway容器镜像标识为 `sha256:817c7c3a8bf9ec233c97875de7d35e00d61862886e884bd09d69946aadd54819`，OCI标签为OpenClaw **2026.9.4**、revision `3a9d69db306cd7f081e06254cb89c4bcc14a7107`。当次日志路径指向`/app/dist`，与该部署结构相符。容器内Rastermill为0.3.2。可读源码checkout `/home/chen/openclaw` 是较旧的2026.6.10；精确运行实现以下以容器内2026.9.4 bundle为准，bundle注释保留了原源码文件名。

## 注册与为何M3能调用

实际部署bundle `/app/dist/openclaw-tools-Bo9W_tg_.mjs:7040` 的源码标记为 `src/agents/tools/image-tool.ts`，定义 `name: "view_image"`、参数`path/paths`、`maxBytesMb`和`maxImages`。同一文件 `:6596` 的 `src/agents/tools/image-tool.result.ts` 构造`type:image`内容块，并调用`sanitizeToolResultImages`。OpenClaw核心工具组会把已创建的媒体工具列入核心工具清单；这不是由某个`view_image`插件注册。插件启动记录中也没有名为`view_image`的插件。

运行bundle `/app/dist/dynamic-tools-B3iuVIOQ.mjs:147` 的Codex规则只在Codex原生图像检查能力可用时移除OpenClaw的同名工具。当前任务走MiniMax M3图像输入路线，未由Codex原生查看器替代；日志记有M3会话实际`tool=view_image`调用，结果带原生图像块。

更直接的证据是**提示明确要求使用它**：私有执行副本 `runtime/paddleocr-vl-evaluation/m3-eval-r1/executed/prompts/page-11-direct.md:1` 写明“必须使用内置图片查看工具实际打开”；复核提示也有同样要求。仓库生成模板可见 [prepare_m3_ocr_comparison.py](/home/chen/dev/openclaw-filetools-dev/runtime/paddleocr-vl-evaluation/repo/scripts/prepare_m3_ocr_comparison.py:41) 和第76行。因此应更正先前可能造成的印象：这些调用不是模型在没有指令时自行决定查看图片，而是按测评提示调用。

当次page-11日志的脱敏定位为私有文件`runtime/paddleocr-vl-evaluation/m3-eval-r1/executed/responses/direct/page-11.stderr`第133–142行：先加载图片路径、随后记录工具调用和返回。未将私有会话原文或日志提交Git。每次传输的图像MIME、尺寸和SHA已脱敏保存在[传输证据](evidence/ocr-m3-image-transport-v1.json)。

## 1819×2573 PNG如何变为848×1200 JPEG

这是两个连续的OpenClaw处理阶段，不是MiniMax在API入口秘密缩图：

1. 核心`view_image`加载PNG时调用媒体模块`loadWebMedia`。运行bundle `/app/dist/openclaw-tools-Bo9W_tg_.mjs` 的`src/agents/tools/image-tool.ts`区域动态载入`web-media-CEQXXM3s.mjs`；该shim再载入实际实现`/app/dist/web-media-vOBnq1w4.mjs`。此调用没有给原生M3路线传`imageCompression`策略。媒体实现默认最长边2048px，单图`auto`采用balanced策略，默认JPEG质量候选为80、70、60、50、40，边长候选含2048、1536、1280、1024、800。源码及运行bundle定位：`web-media-vOBnq1w4.mjs:306–320, 437–490`。不透明/被优化的图片由Rastermill编码。运行日志在进入工具结果清洗前记录了中间图 **1447×2047、520KB**；这是原PNG按2048边界等比收缩后的尺寸。
2. `buildNativeImageToolResult`把该图作为原生`image`块返回，并调用核心sanitizer。`/app/dist/image-sanitization-DhkMOJXD.mjs:2` 定义默认最长边 **1200px**、默认字节上限 **5MiB**；`/app/dist/tool-images-COuyzbFE.mjs:86, 115–149` 读取尺寸，超过限制时按边长/质量候选用Rastermill重编码JPEG。图像传输证据记录最终M3上下文中的JPEG为 **848×1200**；page-11 SHA-256 `26a10c0b703d0f5005e766330f0cd7a1435f75f8e5200e5983fdf3f5819c3253`，268,330字节。日志里工具输出清洗摘要为约262KB，与该尺寸及MIME相符。

第一阶段的实际JPEG质量值未保存在该次审计记录中；只能确认默认候选表，不能宣称实际选中了80。第二阶段源码从质量85开始，并在达到限制时返回候选；本次保存的日志摘要没有`outputQuality`结构字段，故确切质量值仍未核实。阶段一/二的压缩百分比和页面可读性变化没有另做图像质量对比。

## 配置范围与影响

`agents.defaults.imageMaxDimensionPx` 是公开配置项，正整数；缺省时`resolveImageSanitizationLimits`返回默认1200。schema帮助文字说明该项控制transcript/tool-result图像清洗。配置定义位于运行bundle `image-sanitization-DhkMOJXD.mjs:2`，可读源码对应 `src/agents/image-sanitization.ts:6–21`、`src/config/zod-schema.agent-defaults.ts:233`、`src/config/schema.help.ts:1459–1460`。当次运行日志显示最终边长1200；历史配置快照没有保留，因此无法判断当时是默认值还是显式设为1200。

它位于`agents.defaults`，没有单次`view_image`最大边长参数，也没有`AgentEntrySchema`级的`imageMaxDimensionPx`字段。`view_image.maxBytesMb`只控制图片加载的字节预算，不是输出分辨率开关。设置`agents.defaults.imageQuality`也不能改变本次原生M3 `view_image`加载阶段，因为这一路没有传入模型压缩policy。

将全局最大边长调高会作用于所有使用该Agent默认值的工具结果图片以及直接提示图片清洗，不限于这五页或M3；包括`view_image`、读图工具、截图/节点媒体结果和后续历史图像清洗。可能增加上下文图像token、网络负载、延迟和内存，也可能撞到其他模型的尺寸或字节限制；5MiB工具结果上限及provider约束仍然存在。这不是单次调用或仅当前Agent的隔离开关。

## 是否能绕过工具传原图

**文档支持：可以。**MiniMax中国区官方[Anthropic SDK文档](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)说明，Anthropic兼容Messages的M3支持`type=image`，可通过URL或base64发送JPEG、PNG、GIF、WEBP；单图最大10MB，请求体最大64MB（文档“Messages字段支持”，约第199–216行）。本次五张原PNG为1.89–2.23MB，处于文档单图大小范围。使用同一M3 Anthropic消息端点，以图片内容块直接构造请求，不经过OpenClaw `view_image`的`buildNativeImageToolResult`和工具结果sanitizer，技术上可以保留原图或发送高清裁片。

**未验证：**本轮未向MiniMax直接发送原PNG或裁片，未测试实际端点对原分辨率输入的接受情况、图像token用量或识别差异。通过OpenClaw提示中的文件路径、`view_image`或`image`核心工具仍会经过各自媒体清洗；这不能证明能绕过上述限制。此前M3图像成功调用只验证了OpenClaw处理后的848×1200 JPEG到达模型。

## 最小修改建议

先保留1200px全局默认。若需高分辨率重测，在OpenClaw核心增加显式请求级高分辨率选项，让它同时控制媒体加载阶段和工具结果清洗阶段；只允许严格的边长/总像素/字节上限内选择，默认路线不变，并逐请求记录源/中间/最终尺寸、MIME、SHA和实际编码质量。这样可隔离影响范围。另一条独立实验路径是直接用现有MiniMax Anthropic API构造M3 image content块，绕过OpenClaw图像工具；它需要单独记录调用与费用，且本次尚未验证。当前不建议直接提高全局配置来验证这一专项问题。

本报告为只读源码/运行证据分析；未修改或重启生产服务，未修改配置/代码。未读取凭据和完整私人会话。
