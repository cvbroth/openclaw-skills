# M3原图直接转写50页实验（2026-10-07）

**50个不同页面均已尝试；49页获得原始转写，物理第136页失败。共51次请求（含一次显式重试）、2次失败尝试、0次max_tokens截断。人工审核全部空白，未测准确率。** 失败页两次均为HTTP500、api_error、`output new_sensitive (1027)`；没有转写或usage。此处只记录提供商错误，不推定其判定依据、不按识别错误计分，也不将缺失用量填为0。

沿用测评分支 `eval/filetools-paddleocr-vl-20261006`，基线 `6f7dbc23bb0630f1ebf517dbdd95525cc88657fc`，包含e0adc006及既有OCR/离线复核成果。外层868c25d文档工作区未提交改动保留。启动前没有正在运行的M3实验容器；本轮没有复用历史模型转写，没有运行本地OCR、生成正式题册、部署或入库。

## 输入与固定取样

指定《27版肖1000试题分册.pdf》，SHA-256 `0007677dc510b01ffed36bd1250fafd8a7b0101f383e3603257b45e379a6f28b`，执行前后相同。只读单文件挂载；仅渲染选中的50页，无NAS业务扫描。

种子 **2026100701**；Python3.12.10 `random.Random(seed).sample` 从物理6–169页中排除23，均匀无放回抽49页，再加入23、排序。样本固定后未因难易或失败换页，总数50：

12、15、16、18、23、28、29、31、36、37、39、40、42、44、47、50、52、53、55、60、62、68、70、71、75、81、82、83、87、92、94、95、97、100、101、106、115、116、118、129、136、139、140、141、150、155、160、163、166、168。

PyMuPDF1.25.5，220dpi、RGB、annots=False。50张PNG均1819×2573，单图1,706,950–2,387,183字节，合计102,279,471字节。清单SHA-256 `9ff00926abb49d4d8b3300ee2ec741fd80b9d93b49d6d7e6da75ef2e11eaca9d`，记录每图哈希/尺寸/渲染时间。

## 原图上传调查与实际验证

旧OpenClaw核心view_image有媒体加载2048px和工具清洗1200px两个阶段，曾把1819×2573 PNG变成848×1200 JPEG，详见[已有调用链报告](VIEW_IMAGE_M3_CALL_CHAIN_REPORT.md)。本轮没有修改该工具、全局图片配置或生产服务。

[MiniMax官方Anthropic文档](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)支持M3的PNG base64图片输入，单图上限10MB。本轮复用既有MiniMax中国区端点 `https://api.minimaxi.com/anthropic/v1/messages`、同一SecretRef凭据，直接构造Anthropic Messages HTTP请求，绕过OpenClaw工具及其图片清洗。凭据由现有运行组件单键只读解析，经内存管道/FIFO传给独立容器，不输出、不写文件、不挂载生产状态目录。这是已授权隔离客户端实验，不是新增FileTools正式工具。

先以第12页验证，HTTP200、returned_model=MiniMax-M3、end_turn；这一页计入50页，后续跳过而非另增探针。该页实际序列化请求图片解码后为PNG、1819×2573、2,254,983字节，SHA `81d706884884e0610632493c29b56250aea4fc164096c7db6b10026a8ebc034c`，与源PNG逐字节一致。

随后全部使用同一方式。离线审计51次实际发送前保存的请求体，逐一解码图片并核对源文件、尺寸、MIME、字节数和SHA；**全部一致，无客户端缩放或JPEG有损重编码**。第136页两次请求体SHA也完全相同。Pillow11.1.0只读检查尺寸/格式，不重编码。

保留的是220dpi渲染PNG的像素尺寸与文件字节，不是宣称恢复PDF扫描前的细节。服务未回传内部图像或预处理记录；**M3服务内部是否缩放、如何编码及实际视觉处理分辨率仍未知**。HTTP成功和base64方式本身不能证明模型内部原分辨率处理，更不能证明识别更准确。

## 请求、进度与时间用量

请求/成功响应均标识MiniMax-M3；每页一个新请求，仅一张原图和相同指令，无系统提示、工具、会话历史、OCR、参考、答案或质量反馈。第23页的指定身份和历史受损评价未进入请求。thinking=disabled、temperature=1、max_tokens=12000、service_tier=standard、非流式；仅要求原文转写，不输出评分/总结。

首次49成功、1失败；第136页经过一次有界追加重试仍失败，原失败与重试均保留，不再重试、不换模型、不缩图规避失败。主文本固定取最新尝试，界面展示所有尝试状态和原始响应，不择优。原始响应字节与转写文本保留，未人工纠错/清理；49份转写均和原始响应text内容一致。end_turn仅代表接口正常结束，不代表全文完整或遵守指令已获验收。

51次请求客户端墙钟耗时合计 **547.382秒**，单次最短6.917秒、中位9.859秒、最长22.900秒；包含两次失败，不含准备、渲染、隔离启动、浏览器和打包时间，不冒称后端计算时间。Unix信号及网络超时180秒，未扩限。每页终态及时写入；真正detached容器不依赖终端，续跑跳过已有尝试。有一个最初nohup启动在创建容器前未存续，没有产生提供商请求，后改为detached容器；不隐去或混算调用。

49次成功响应可见usage合计：input_tokens **185906**、output_tokens **35002**、cache_read_input_tokens **6272**、cache_creation_input_tokens **0**。失败两次未返回usage，费用/套餐消耗不可得，不能据此宣称0费用。缓存由提供商记录，不意味着携带了前页聊天历史。未返回图片token明细、远端处理耗时或内部资源；没有推算账单或整册速度/费用。

客户端固定镜像 `filetools-document-test:20261006-364d4d6`，实际ID `sha256:edb3ca0710298ff4fe36a613dfdd2ee295f750c90cf60ebe602d6d319b85adbe`。独立容器2CPU、2GiB，memory-swap总额度2GiB，无额外swap，UID/GID1000，只读根、cap-drop ALL、no-new-privileges、tmpfs128MiB；API阶段bridge出口，未开放端口。这里不是生产Worker额度，也不是远端M3内存。生产Gateway/Worker镜像及启动时间保持，Gateway健康仍healthy。

## 真实验证、模拟测试和未验证

- 真实：50页固定渲染、51次M3 API请求；51份原始响应，49份按页原始转写；51次请求PNG保真审计；原件哈希不变；ZIP完整性和共享复制后哈希检查。
- 真实离线浏览器：Playwright既有环境、Chromium140.0.7339.16，file://、offline模式；检查全部50页原图加载、转写一致展示、双栏边界、空白审核及50行导出，无JS错误或外部请求。初次预览发现图片撑宽双栏，修复minmax(0,1fr)后复验。开发侧查看12/23/168界面截图，属于展示检查，不是50页逐字人工验收。
- 合成代码测试7项通过：可复现取样、PNG字节/尺寸保留、原始文本和截断、断点不覆盖、HTML安全与空白审核、追加重试/失败用量、审计篡改拒绝。Ruff和编译/差异检查通过。最初Ruff缓存因只读挂载失败，改为--no-cache后通过，没有扩大权限。浏览器模拟编辑仅在内存测试，未导入确认或交付用户标注。
- 未验证：49页转写准确性/遗漏/题号和顺序、用户Windows浏览器与下载、用户真实审核、M3内部缩放及真实账单。未计算CER或准确率，也没有由模型或开发Agent填写人工等级。第136页没有可评估转写。

通用脚本、操作说明见[M3隔离实验说明](M3_ORIGINAL_IMAGE_TRANSCRIPTION.md)；脱敏逐次证据见[evidence/m3-original50-audit-v1.json](evidence/m3-original50-audit-v1.json)，浏览器及合成测试见同目录m3-original50文件。原始PNG、请求体、完整响应、预览/截图和确认测试留在私有忽略目录 `runtime/paddleocr-vl-evaluation/m3-original50-r1/`，不提交Git。历史五页结果及原OCR未覆盖，不混入本轮统计。

## 用户交付

最终包 `filetools-m3-original50-20261007.zip`：**100,787,034字节**，SHA-256 **4f9dd478dc32f1479ee1f5d0cb3ffeb7b39bd45b1329b1b92eff7ad34362da9d**。

服务器交付目录 `/srv/storage/users/chen/FileTools-Deliveries/m3-original50-20261007/`；Windows `\\myserver\Chen\FileTools-Deliveries\m3-original50-20261007\filetools-m3-original50-20261007.zip`。Chen Samba共享根为`/srv/storage/users/chen`。现有Gateway/Worker仅挂载该根下FileTools-Incoming子目录，本独立交付目录不在其Incoming或Agent工作区挂载内，不会成为输入来源。新建目录不覆盖旧文件；复制哈希与开发包一致。未调用FileTools saved或知识库接口。

解压全部文件，打开index.html；第23页可用index.html#page-23直接进入。点击原图打开原尺寸，右侧可复制原始转写，展开调用记录或打开每次完整响应。按页文本在transcriptions/，汇总在SUMMARY.md/summary.json。第136页可查看两次失败响应，没有伪造转写。全部人工等级和备注默认空白；请自行填写并导出审核JSON，刷新前先导出。审核数据只存在用户当前浏览器内存/导出文件，不自动回写服务器。

本轮停在审核包交付；等待用户人工判断，不推进生产或整册正式生成。
