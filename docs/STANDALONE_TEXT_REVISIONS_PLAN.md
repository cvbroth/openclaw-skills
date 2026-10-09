# R7 人工文字修补：实施计划与数据约定

基于 R6 增量开发，仅独立 HTTP 服务。没有 OCR、云端调用或生产部署。

1. 独立修订模块验证已登记 Markdown、页级稳定 locator、文件与页面哈希；无明确映射时拒绝编辑。
2. 每次保存物化完整新稿、逐页安全阅读数据、同步结构 JSON 和独立修订日志。空串表示删除；无变化返回原稿。历史不覆盖。
3. 请求携带父产物 ID/SHA、修订链头 ID/SHA、UUID 请求 ID。服务端锁内检查，先准备资源，再原子替换项目登记。重复请求返回原回执；冲突拒绝。
4. 双栏右侧增加逐页编辑、状态、保存、保存后排版、差异和历史恢复。左侧保持独立；切换编辑对象前明确保存／放弃／取消。离线仅阅读。
5. 复用现有 format_artifact 和真实 DOCX/PDF 预览，保存与排版分别报告。合成第23页验证内容一致、历史保持和零引擎调用；真实浏览器检查并导出便携包。

## 数据约定

修订链以最早登记文字产物为 root；project.text_revision_heads 存最新版本。修订产物的 text_revision 指向父稿、链根、修订 ID 与独立日志。日志保存前后完整页文字、来源 locator、时间、actor_type=human-self-declared／developer-agent／unspecified-interface（自行声明，不冒充身份认证）。恢复历史同样创建新版本。

结构文件保存 source_sha256、逐页物理来源、稳定 locator、正文及 Markdown AST。改写页 coordinates=null；已有坐标只能作为来源证据，不声明新字的精确位置。质量、评论与原响应仍独立，修订不等于原图或整页人工验收。

接口：GET text/:artifact；POST text-revisions；GET text-diff/:artifact?against=ID。请求仅允许登记 ID、locator 和文字，不接受路径。保存返回新 artifact_id、no_change、replayed 和 engine_calls=0。排版使用原有独立 POST format。
