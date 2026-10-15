# FileTools Pandoc运行与更新

本轮只更新`filetools-http-dev-review-r3`，继续使用日常开发分支只读源码挂载、`runtime/standalone-http-r1/data`和原`config.json`。其他NAS/OpenClaw容器不动。

## 可重复依赖

从官方发布下载`pandoc-3.6.4-linux-amd64.tar.gz`，本轮使用的完整压缩包SHA256：

```
5def6e1ff535e397becce292ee97767a947306150b9fb1488003b67ac3417c5e
```

将文件命名为`pandoc-3.6.4.tar.gz`放入构建上下文，使用仓库`deploy/Dockerfile.pandoc`构建。该Dockerfile会验证哈希、安装到`/opt/pandoc-3.6.4`并创建`/usr/local/bin/pandoc`。基础镜像`filetools-http-dev:reading-pdf-20261012`的已验证ID：`sha256:9ee7d4f259e65b4cdefd37bbce68021eee25e1a0ab6f3d3cf13464c27ebba44b`。保留其中LibreOffice7.4.7.2、Python3.12.10和中文字体，移除Playwright与`/opt/filetools-browsers`。

新镜像：`filetools-http-dev:pandoc-20261015`。版本化`src/nas_filetools/standalone/reference.docx`是默认参考文件。需要未来更换样式时发布新的参考版本并保留哈希；每项任务在接受时复制参考文件，后续更新不能改动既有导出。

运行检查：Pandoc、LibreOffice可执行；Droid主字体及`fonts/manifest.json`对应补充字体哈希正确。DOCX先经字体补充和验证，再由LibreOffice转换为PDF。不能配置浏览器PDF或自写Word正文生成器作为回退。

## 日常部署步骤

1. 检查实际Git分支、工作区与远端；保留未提交修改。检查提取、分析、预览与导出活动任务，有任务则等待。
2. 备份每个项目元数据，记录现有文件、原件、文字、历史导出、评论、诊断与配置哈希；页面派生资产允许更新，正文资源不改写。
3. 在隔离数据根验证镜像与实际Word/PDF、真实浏览器流程。
4. 推送已验证提交。停止空闲的日常服务，快进日常开发工作区；以新镜像重建同名服务，保留原挂载、用户、CPU/内存限制、环境和监听地址。原容器改名保留为停止状态的回退记录。
5. 检查首页、当前SHA、Pandoc/Office版本；通过日常界面生成实际文件并下载，检查旧文件及评论配置哈希，确认没有活动任务遗留。

回退应恢复一套一致的代码/镜像，不能只启用缺少Pandoc的旧镜像配新代码。优先对迁移提交执行Git revert形成新提交，再用对应镜像启动；不恢复或覆盖数据根，新增修订和导出继续保留。任何回退前仍须等待业务任务结束。

构建包、配置、原件、模型凭证及真实文档不得提交公共仓库。私有交付包仅含选择后的报告、证据、实际导出与代码补丁，不含运行配置或密钥。
