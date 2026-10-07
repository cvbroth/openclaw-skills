# M3原图直接转写隔离实验

这是开发实验脚本，未接入生产FileTools，不运行OCR，不产生正式题册或人类确认。沿用MiniMax中国区既有凭据和 `https://api.minimaxi.com/anthropic/v1/messages`，固定 `MiniMax-M3`，不使用其他供应商。接口依据：[MiniMax官方Anthropic SDK文档](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)。官方支持PNG base64图片输入；这不保证服务内部不缩放。

## 固定输入和请求

`scripts/m3_image_transcription.py prepare` 接收确切PDF文件、预期SHA、随机种子及新输出目录。仅从物理6–169页抽样，固定23页，再从其余163页以Python `random.Random(seed).sample` 无放回抽取；总数默认50。220dpi、PyMuPDF1.25.5、RGB、无注释渲染。清单包含种子、算法、页码、源PDF和每张PNG哈希。已有目录拒绝覆盖。不要因为页面难易修改抽样。

`run` 每页只发送一张PNG和相同转写指令，不发送系统/工具提示、OCR、参考或历史会话。`thinking=disabled`、`temperature=1`、`max_tokens=12000`、`service_tier=standard`、非流式。每页请求有180秒Unix信号截止和网络超时。Pillow只读检查格式和尺寸；编码请求后再次解码base64，逐字节核对源PNG、尺寸和SHA。原文件不是先转成JPEG再base64。

凭据只从stdin读取，保留在进程内存；不把密钥放进命令行、环境变量、请求审计文件或日志。部署专用启动器可以通过OpenClaw已有 `readSecretStoreValue` 的单键只读接口解析现有SecretRef，使用内存管道/FIFO把结果送入隔离容器；不得输出到终端或落盘，不挂载完整生产状态目录。此适配依赖当前OpenClaw运行bundle，版本变更需核对路径，不能把编译文件名当成稳定公共SDK。

建议复用固定开发镜像 `filetools-document-test:20261006-364d4d6`，ID `sha256:edb3ca0710298ff4fe36a613dfdd2ee295f750c90cf60ebe602d6d319b85adbe`，Python入口 `/opt/nas-filetools/.venv/bin/python`。仅渲染时单文件只读挂载授权PDF、关闭网络；API实验时使用独立bridge网络，无端口，无生产业务目录、Docker socket或生产配置挂载。2CPU、2GiB、memory-swap=2GiB、只读根、非root、cap-drop ALL、no-new-privileges。这里的资源仅为客户端，不代表远端M3资源。

## 断点和原始证据

- 准备清单固定后先运行 `run --limit 1` 验证原图渠道。这一页计入50页，后续 `run` 跳过已有尝试。
- 使用真正detached容器，不依赖终端或短命的nohup启动进程。可在容器tmpfs建立0600 FIFO，让启动进程等待凭据；通过只读凭据解析管道输入，密钥不会储存在FIFO文件中。逐页回执即时写入，进度写容器stdout，只输出元数据。
- 每页 `attempts/page-N/attempt-1` 保留无认证头的完整请求体、完整响应字节、回执和未经strip/纠错的转写。多text块仅按返回顺序直接连接；块边界仍在原始JSON中。
- `max_tokens`明确标记截断；HTTP/客户端/空文本错误分别留痕；未调用、未完成和异常停止理由不填为成功。401/403/429停止后续调用。没有静默重试或最佳结果筛选。
- 默认续跑只处理从未创建尝试目录的页，不覆盖失败或中断记录。仅对已失败或截断页，可显式使用 `--retry-page N --retry-reason 原因` 进行最多一次重试，追加attempt-2，不覆盖attempt-1。成功页和运行中页拒绝重试。审核包展示两次状态和原始响应，主文本固定显示最新尝试，不择优。所有尝试耗时和可见用量均纳入汇总；失败未返回用量时标明不可得。
- 原图保留只读；请求体、完整响应、PNG、用户审核及截图必须留在忽略目录，不上传Git。

## 离线人工审核

`bundle --directory PRIVATE_EXPERIMENT --output NEW_BUNDLE --zip NEW_ZIP` 产生离线 `index.html`、逐页原始转写、响应、回执、PNG和汇总Markdown/JSON。源图与提交图字节相同时共用同一图片入口，展示双方哈希及尺寸；不制造第二份假“模型内部图”。服务内部处理保持未知。

HTML以textContent/textarea.value展示模型文字，内嵌JSON转义脚本分隔字符。所有人工字段初始为空，可选择基本准确／有少量错误／错漏严重／暂无法判断并填写备注，导出JSON。浏览器只保留当前内存草稿，刷新前须导出。导出记录包含源PDF、清单、源图及转写哈希，自报审阅者不等于认证身份；当前不会导入生产账本。

`scripts/browser_smoke_m3_transcription.py` 仅离线检查每页资源、文字一致展示、空白导出和页面切换的草稿保留；模拟编辑不构成人类确认。开发截图可注入既有本地中文字体，字体不随包分发。用户端浏览器、实际转写准确性及模型内部处理均需另外验证，自动测试不能代替人工看图。
