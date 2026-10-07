# OCR/M3开发对照入口

这是显式授权页面的独立开发实验，非生产工具；不新增模型SDK依赖，不自动访问API。模型调用须使用已授权MiniMax渠道，不因主机import失败判断Worker能力。原OCR、图片、参考、模型响应、确认JSON及包只放忽略目录。报告见 [OCR_M3_COMPARISON_REPORT.md](OCR_M3_COMPARISON_REPORT.md)。

1. `scripts/prepare_m3_ocr_comparison.py --snapshot FILE --images DIR --config deploy/ocr-m3-comparison-v1.json --output NEW_PRIVATE_DIR --container-root ABSOLUTE_AUTHORIZED_IMAGE_DIR --pages 11 23 114 127 131`。需要项目固定Pillow；校验固定图哈希，生成原图副本、裁片、独立提示和清单，不发请求。B无OCR，C按风险选区，过滤历史源图受损标签；全页风险吞并局部区域是当前已知限制。
2. 本轮实际渠道为现有Chen状态目录的 `openclaw agent exec --state-dir /home/node/.openclaw/agents/chen/agent --cwd /home/node/.openclaw/workspace-chen/filetools-m3-eval-20261007/prepared --model minimax-portal/MiniMax-M3 --thinking off --timeout 180 --json --message-file prompts/page-11-direct.md`。这是实际授权开发调用示例，不是新FileTools工具，也非QQ入站；不自动循环其他页或重试、不发送消息。各页/路线单独调用，响应、stderr、开始/结束时间及退出码落盘。日志可能含正文/会话信息，不能提交。检查原生image工具块及实际尺寸，而非相信模型自报尺寸或路径字符串。
3. `scripts/evaluate_m3_ocr_comparison.py`参数：`--config --snapshot --manifest --reference --additional-reference --batch --reviews --images --responses --output`均为必需路径；只对本轮五页计算。参考必须来自看图，排除源图无法辨认区域且留历史；不得用模型输出建真值。输出private-analysis、summary-private与白名单summary-redacted。格式失败仅有界取字段用于诊断，保留raw、strict_json=false和复核阻塞，不自动认证。
4. `scripts/build_m3_comparison_demo.py --bundle EXISTING_OFFLINE_BUNDLE --analysis PRIVATE_ANALYSIS_JSON --summary PRIVATE_SUMMARY_JSON --executed PRIVATE_EXECUTED_DIR --output NEW_DIR --zip PRIVATE_ZIP`；复用既有确认界面，增加comparison.html/裁片/原响应，全部未确认；模型建议仅构造衍生副本，不进入人类ledger。通过既有离线确认JSON导出/校验导入时仍需真实审阅者、哈希和版本，不能导入模型keep冒充用户。

配置version及SHA记录在报告；准备提示和最终评分配置必须分别留SHA，不改历史提示。五项等级good/minor/major/unknown的视觉锚点写在准备脚本；程序按已知权重归一化，低于minimum_known_weight则未知，关键风险封顶且阻塞。权重正数且和为1；等级值0–100严格递减；已知权重门槛(0,1]；风险阈值0–100有序；裁片padding/merge整数0–500，区域上限1–50，抽查比例0–1。未知键、缺组、非有限数、布尔数字、无效坐标/枚举拒绝。强制复核条件不能删掉。分数不是准确率，参数初始未经统计校准，不以调参把样本全部放行为目标。

系统建议与人工状态分开；没有覆盖证据为未知，有内容/顺序阻塞即需复核，源图受损需更清晰来源。正常页按配置/图哈希确定性抽查，未抽中也不标人工通过。所有模型修订保留来源、ID、前后文字；无目标、未知/重复ID、冲突或大比例删字不能悄悄应用。当前位置/非正文建议仅展示，不自动删除和排序。

开发验证命令：`python -m unittest discover -s tests -p 'test_ocr_m3_comparison.py'`，并运行既有offline bundle及spatial tests。Ruff固定0.11.2。可选Playwright1.55.0/Chromium140.0.7339.16用于 `scripts/browser_smoke_m3_comparison.py --help` 的离线浏览器测试，非生产运行依赖；浏览器/系统库仅在/tmp准备。真实输出、模型自评、代码测试、开发源图核对和用户确认分别报告。
