# 独立 HTTP 文件项目（开发版）

最新批量任务与管理行为见 [批量提取说明](STANDALONE_BATCH.md)：单任务选页1000，打印机式范围，产物回收/任务归档及稳定ID评审链接。历史报告中的5页是原阶段限制。

入口为 `python -m nas_filetools.standalone.http --root PRIVATE_STORE --config PRIVATE_CONFIG`。核心不依赖 OpenClaw、QQ、Agent 会话或插件目录；当前仅用于可信单人、loopback 开发环境，未部署为生产服务。不是公开文件服务器、NAS 索引或多用户平台。

## 启动与访问

依赖复用项目固定版本：Python 3.11/3.12、PyMuPDF 1.25.5、python-docx 1.1.2、Pillow 11.1.0；本地 OCR 另需 `rapidocr-onnxruntime==1.4.4`、`onnxruntime==1.20.1`、`numpy==1.26.4`。字体使用既有固定 Droid Sans Fallback。没有新增 Web 框架或浏览器运行依赖。R2 的实际 Word 逐页预览新增 LibreOffice Writer 运行依赖（已实测7.4.7.2及既有中文字体）；PDF预览复用PyMuPDF。pytest/Chromium/Poppler/PDFium仅用于开发验证。详见 STANDALONE_REVIEW_R2_REPORT.md。

复制 `deploy/standalone-http.example.json` 到私有目录，修改受信任的服务端配置。凭据可沿用环境变量；新增写入式私有设置及迁移见 STANDALONE_UPLOAD_ANALYSIS.md。密钥不进入项目或公开配置。可直接在独立虚拟环境启动；现有服务器推荐复用已固定候选镜像作为**新的开发容器**：

```bash
scripts/launch_standalone_http.sh "$PRIVATE_STORE" "$PRIVATE_CONFIG" \
  sha256:3bf4eabd2e4cde9521c212568359f416c6ab9d06709f3d677e8cdaa84efe8530 \
  filetools-http-dev-example
```

可选第五参数是凭据环境变量名，启动器从标准输入接收一个密钥，经私有 FIFO 交给服务。不要把密钥放在命令参数、shell 历史或日志中；应用自身不调用 OpenClaw 获取认证。历史测试实例曾通过单密钥引导；本轮开发实例未配置远端密钥，远端显示待配置。停止/重启只针对自建 `filetools-http-dev-*` 容器，先检查所有任务终态。保留 store 即保留任务、产物与评论；每个 store 仅允许一个服务进程。

当前监听 `127.0.0.1:18971`。Windows 终端建立转发后，浏览器打开本机地址：

```bash
ssh -N -L 18971:127.0.0.1:18971 chen@myserver
```

访问 `http://127.0.0.1:18971/`。若本机端口占用，可用 `-L 18972:127.0.0.1:18971`，但当前 Host/Origin 检查只允许服务端配置端口，因此建议先释放本机18971；不随意放开校验。不要将此无认证开发服务绑定到公网。启动器用 host 网络是为支持 loopback 和既有出站请求，HTTP 自身仍只绑定127.0.0.1。

## 使用

1. 首页只选择 PDF/PNG/JPEG/WebP 及可选项目名，上传创建项目；不自动识别或排版。后台原件分析单独显示状态。进入详情后明确选择方法和物理页，最多1000页/转换任务。上传与分析契约、限制及设置见 [上传与分析说明](STANDALONE_UPLOAD_ANALYSIS.md)。
2. 项目默认以文件名命名。可改名、查看逐页进度、取消、只重试未成功页。切换引擎明确新建任务，保留原任务与全部产物。服务不会自动重试付费请求。取消只停止本地等待/子进程，不能保证远端未计费。
3. “复用识别重新生成文档”不请求任何识别引擎，追加结果版本；适用于格式修复或改名后的重新排版。成功页不重跑。不会修改公共模板。
4. 列表点击进入独立 `/projects/<id>` 详情，评审左右独立选择、翻页、缩放和滚动。PDF使用后台逐页图片；Word使用LibreOffice对实际DOCX渲染的图片，不借用独立PDF。预览失败显示真实错误并可重试，不能当作成功；导出包含已生成预览。无分页映射时不推断对应关系。
5. 评论输入先存本地草稿，再保存到服务；版本冲突保留草稿并报错，不静默覆盖。清除产生空评论记录，历史回执仍保留。导入时校验项目、产物ID/哈希、定位和版本；草稿冲突需明确采用导入版本并先下载备份。切换参考不会让目标评论消失。关闭页面前应确认“已保存到服务”，或导出 JSON。
6. 下载单产物或整个项目包。导出包可解压后离线打开 `review/index.html`；离线评论需导出再导入服务，浏览器不能直接写服务器。回收站仅移动项目，恢复后保留产物和评论；没有永久删除接口，也不访问/删除外部原件引用。

原图质量独立关联源页、实际传图哈希/尺寸、模型和任务，可查看多次记录。筛选“原图质量”只改变原件名单，不因右侧产物切换而变化。模型质量是未经校准的自评，本地 RapidOCR 不提供视觉质量自评且不覆盖已有评价。筛选“未提供评价”不等于错误或差。人工评论与模型评价分别存储，都不写入正式 Markdown/Word/PDF，也不构成人工验收。

## 配置与能力

配置 `version=1`，分 `service / engines / conversion / template`，未知字段/非法范围拒绝。上传1KiB–512MiB（默认100MiB）、文件页数1–1000（默认200）、像素0.1–40M（默认20M）、DPI100–300（默认220），单任务显式选择1–20张（默认最多5张）。PDF只渲染选中页；静态图片原字节传入，不有损重编码。远端适配器另限每图20MiB，超限报错，不缩小图片。上传后会验证文件签名、扩展名和图片帧数；动图、多帧及其他类型不支持。

| 适配器 | 协议与实际能力 | 验证范围 |
|---|---|---|
| rapidocr | 本地CPU，原生行文字/坐标/分数；不提供原图视觉质量评价 | 本轮合成图及授权第12页真实运行 |
| minimax-messages | MiniMax原生Anthropic messages，原字节base64，独立转写与质量JSON | 本轮2次真实MiniMax-M3请求 |
| openai-vision | 配置的chat-completions端点、image_url data URI；提示分段质量 | 本地mock协议验证；没有真实兼容端点凭据，非全厂商兼容承诺 |

所有引擎 `concurrency=1 / retries=0`，CPU线程1–2，超时1–1800秒（示例180）。本轮仅单队列，不自动路由。远端不跟随重定向，避免隐式转发认证；地址只接受无认证/查询参数的HTTPS，测试模式允许loopback mock。参考协议：[OpenAI图片输入说明](https://platform.openai.com/docs/guides/images-vision)。这只说明消息协议，不证明任意供应商兼容。

运行配置的凭据引用从项目快照删除；密钥值只在服务和对应子进程内存。原响应保留，但若提供商回显密钥则替换为 `[REDACTED]`。响应限8MiB，错误体1MiB，异常消息不包含网络认证内容。配置文件可信且不由浏览器编辑。服务限制对**整个新容器**生效：2CPU、4GiB、memory-swap=4GiB、只读根、UID/GID1000、无额外capabilities；生产Worker额度完全不变。子任务是可取消进程，不宣称这是面向不可信代码的完整安全沙箱，也不执行用户上传Python。

模板沿用已发布 `questions-zh-cn/1.0.0`，记录快照哈希。仅无解析疑点的同类单选结构使用题干/选项样式；其他结构保留原文为“待核对片段”，不猜编号/归属、不删页眉、不去掉Markdown语法来冒充可靠整理。后者允许自然跨页，不保证题目语义分页。尚不支持任意论文/图书/公式/表格结构恢复。Word字体未嵌入，客户端替换风险仍在；模板/原生检查不代替逐份视觉验收。

## 模块、数据与接口

- `standalone/http.py`、`standalone/assets/`：HTTP校验、流式上传、管理UI、下载、评语接口。管理界面只按引擎清单选择，不绑定某模型。
- `standalone/tasks.py`：项目/任务状态、串行队列、选页渲染、子进程期限/取消、失败页重试、产物登记与发布。复用 `publication.publish` 的复制/哈希校验及 `artifact_project` 的产物登记。
- `standalone/adapters.py`、`engine_worker.py`：明确图片/配置→统一结果，不决定项目路径、不生成网页；原生协议可独立扩展。
- `standalone/documents.py`：60秒内的独立格式生成子进程，复用现有成熟库和模板；不重复OCR。

store 布局：

```text
projects/<project_id>/
  project.json
  sources/               # 上传原件、选页预览；旧项目可仅引用外部原件
  content/<task_id>/vN/   # 按页加载的评审文字
  templates/             # 实际用过的配置快照
  outputs/               # 兼容现有项目结构；注册路径才是实际产物入口
  review/                # 同一份HTTP/离线评审数据、原图评价镜像、反馈及追加历史
  previews/<cache_key>/  # 按产物SHA/渲染器/参数缓存的图片及逐次诊断
  diagnostics/tasks/<task_id>/
    page-N/attempt-N/    # request(脱敏)/result/raw.md/原响应/日志
    generation-N/        # work及经校验的published产物
trash/<project_id>/     # 同目录移动，不触及外部引用
uploads/                # 暂存流式上传
```

不能假定产物一定在outputs下；使用project.json注册的相对路径。项目ID按任务创建，不以源SHA合并。每个产物有独立ID/哈希/版本/父产物。文字、结构、质量独立，远端未提供坐标时null；本地OCR坐标明确对应输入图像像素。上传单张图片位置1不等于原PDF第1页，历史PDF页码通过独立来源记录保留。

| HTTP接口 | 行为 |
|---|---|
| GET /api/engines | 脱敏清单、能力及凭据是否可用 |
| POST /api/uploads?filename=...&project_name=... | 原始文件body、单一Content-Length；202返回project_id/analysis_id，无转换task_id |
| GET /；GET /projects/:pid | 列表/独立详情HTML，可刷新、直接访问 |
| GET /api/projects；GET /api/projects/:pid | 列表/详情、任务逐页状态 |
| POST /api/projects/:pid/previews/:artifact_id | `{ "retry":true }`，仅DOCX/PDF产物后台预览；不隐式处理整份原件 |
| PATCH /api/projects/:pid | JSON `{ "name": "文档名称" }` |
| POST /api/projects/:pid/tasks | JSON `{ "engine":"local", "pages":[1] }`，新版本 |
| POST /api/projects/:pid/tasks/:tid/cancel、retry、format | JSON `{}`；format只复用已有结果 |
| GET/POST /api/projects/:pid/feedback | 版本化评语回执，不修改正文 |
| GET /api/projects/:pid/download/:artifact_id | 校验注册路径，支持单段Range |
| GET /api/projects/:pid/export | 任务终态后导出完整离线包 |
| DELETE /api/projects/:pid；GET /api/trash | 移入回收站/列表 |
| POST /api/trash/:pid/restore | JSON `{}`，恢复原项目 |
| GET /p/:pid/review/index.html | 同一项目评审入口 |

状态QUEUED→RUNNING→SUCCEEDED/PARTIAL/FAILED/CANCELLED。服务重启将遗留活动任务标INTERRUPTED，保留每次attempt目录；不自动恢复计费请求。重试只处理未成功页，原成功页及旧产物不覆盖。错误带category=local/remote、实际stage/code/message；格式失败不会当作图片质量差。任务和进度均持久化，单项目不允许同时执行多个任务。

旧项目用 `scripts/import_standalone_project.py --help` 显式复制导入，只读取所指目录，不追随外部原件、不改旧包。导入项目可评审/下载；无可访问输入登记时拒绝追加转换。目录移动不改变内部链接，外部引用不可达明确提示。

## 验收入口与边界

见 `docs/STANDALONE_HTTP_REPORT.md`。测试用fixture仅在显式 `--testing` 中启用，不在普通配置中开放。`scripts/browser_smoke_standalone_http.py` 只启动本地OCR合成测试和缺凭据失败测试，不发云端请求；需开发侧Playwright/Chromium。实际PDF渲染仅在独立验证镜像完成，服务不会自动作全视觉验收。

本轮未接OpenClaw、未配置守护服务/开机启动/公网认证；大文件容量、断电文件系统恢复、恶意PDF防护、多人并发冲突、全册性能尚未验收。API兼容实际厂商、收费/余额及客户端Word显示仍需独立确认。新增页码或点击M3是实际调用，不提供免费假设。

R2布局、迁移与实测：STANDALONE_REVIEW_R2_PLAN.md / STANDALONE_REVIEW_R2_MIGRATION.md / STANDALONE_REVIEW_R2_REPORT.md。当前界面的浏览器回归入口为 scripts/browser_review_r2.py 和 browser_review_r2_edges.py；R1旧浏览器脚本仅为历史验证记录，其旧选择器不作为R2验收入口。


## 上传容量补充

示例与独立开发配置单文件512MiB（536870912字节），PDF最多1000页（包含1000页）、单任务最多5页。PDF上传只检查基本有效性/加密状态/页数，不提取或渲染正文；转换只处理选页。GET /api/limits供界面显示分离限制，超限返回413并清理失败上传。保持64KiB流式写盘。大文件上传不等于整册转换通过；实测见STANDALONE_UPLOAD_512_REPORT.md。

PDF页数调整与真实1000/1001页边界验证见STANDALONE_PDF_1000_REPORT.md；此前容量报告中的200页为当时历史配置。
