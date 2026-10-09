# R7 人工文字修补

仅独立 HTTP 开发服务。原件、原始响应、原始 Markdown 与历史版本不改写。编辑不是 OCR，也不代表内容已核实。

## 使用

从产物“查看 / 对照”进入评审，右侧选择有明确逐页映射的文字稿，点“编辑文字”。编辑框只放当前来源位置；左侧仍可独立翻页。保存修订版后自动选中新稿并保持当前文字位置，不强制左侧跳页。空内容表示人工删除。无变化不创建版本。

“保存并生成 Word/PDF”先保存，再用项目选定模板排版。两项状态分别显示；排版失败不撤销已保存文字，可以在项目中选择修订稿重新排版。没有项目模板时保留修订，提示先选择模板。模板不改变，也不会重新识别。

“版本与差异”可比较原稿或历史稿、切换查看，或将历史完整内容恢复为新版本。历史稿只读，恢复不会覆盖历史。Word/PDF 的“修改对应文字稿”只沿已登记父关系查找，不推断页号对应关系；没有明确父稿时禁用。

切换右侧页、文件、筛选或阅读视图前，有改动时提供保存／放弃／取消。左侧翻页、缩放不丢弃草稿。返回项目也有同样提示。浏览器刷新、关闭或后退跨文档时使用浏览器原生离开保护；它只能提供离开／留下，需先留下并点击保存。草稿不是服务器已保存稿，崩溃或强制结束浏览器的草稿恢复尚不支持。

## 接口与记录

- `GET /api/projects/{project_id}/text/{artifact_id}?locator=JSON`：已登记映射、当前位置文字、父稿及链头哈希、历史列表、项目模板。带 locator 时只返回该位置文字。不带时用于完整版本比较或恢复。
- `POST /api/projects/{project_id}/text-revisions`：`request_id`（UUID）、`parent_artifact_id`、`parent_sha256`、`head_id`、`head_sha256`、`locator`、`text`、可选 `reviewer_type`。恢复时用 `restore_artifact_id` 替代 locator/text。
- `GET /api/projects/{project_id}/text-diff/{artifact_id}?against={history_id}`：同一链的 unified diff。
- 现有 `POST .../format` 负责后续排版，修订模块与 OCR 适配器独立。

冲突返回409；字段、未知ID、未映射位置或不完整映射拒绝。相同请求ID和内容返回原回执，不重复登记；ID被用于不同内容则冲突。当前完整稿与页数据必须符合已有明确组装格式，不以文本推测分段。单段编辑上限500000 UTF-8字节，HTTP JSON上限沿用1MiB。

保存先创建独立完整 Markdown、逐页 JS、安全阅读 HTML、同步 Markdown AST 结构和修订记录，再一次原子替换项目登记。失败清理未提交目录；进程突然断电后可能留下未登记目录，不把它称为已保存版本。项目反馈版本不因新增文字稿失效；评论仍绑定原 artifact ID/SHA，旧评论不会自动复制成新稿的确认。

`content/revisions/{revision_id}/`：

- `content.md`：完整新稿，无自动加入的修订日志、质量或评论。
- `page-N.js`：逐位置文字及安全阅读视图，含资源哈希。
- `structure.json`：原件SHA、稳定locator、物理来源页、正文及AST。改写文字没有精确坐标；坐标字段null，原始产物仍可作为来源证据。
- `revision.json`：项目、父稿ID/SHA、链根、时间、前后文字、恢复来源、审阅者自声明类型。开发测试使用developer-agent；human-self-declared不是认证身份或人工验收。

## 兼容与边界

无需搬动旧文件或重新OCR。项目新增text_revision_heads、text_revision_requests以及修订产物记录；旧项目只有完整且校验一致的映射才能编辑。无映射/缺资源/哈希不符时说明原因，不开放任意路径编辑。

离线包可以切换历史稿、查看已有预览、下载正文和修订日志；不能保存到HTTP服务，编辑按钮明确禁用。评论导出能力沿用。Windows兼容路径与ZIP CRC已检查，实际Windows客户端解压需用户验证。

现有启动方式不变，见独立HTTP启动说明及R6文档。只重启独立开发服务加载Python接口；没有生产部署、OpenClaw接入、云端调用或自动纠错。
