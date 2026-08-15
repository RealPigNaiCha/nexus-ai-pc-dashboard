# 隐私与安全说明

本分发包是干净构建，不包含制作者电脑上的以下内容：

- API 密钥、Token、Cookie、登录态或 Windows Credential Manager 内容；
- 真实 SQLite 数据库、Zotero 数据库、个人 PDF/笔记、向量索引；
- 日志、历史备份、浏览器数据、Codex 个人配置；
- 原开发环境的 `.venv`、缓存、Git 元数据和临时文件。

Dashboard 默认只监听 `127.0.0.1:8765`。模型生成和显式联网检索可能向所选服务商发送完成任务所需的提示词或最小资料片段；使用前应阅读服务商隐私条款，不要导入无权处理的敏感资料。

API 密钥通过 Windows Credential Manager 保存。不要把密钥写入 Markdown、截图、日志、批处理文件或聊天消息。

分发包的 `manifest.json` 记录所有随包文件的 SHA-256。安装器会先验证清单，任何文件缺失或被修改都会中止安装。

完整版安装器会从 DeepTutor 官方 GitHub 仓库的固定提交下载一次源码，并从 Python 软件包索引下载锁定的 CLI 运行依赖；源码只存放在系统临时目录，非 editable 安装完成后立即删除。安装器不会把 API 密钥、个人资料或 Dashboard 数据发送给 DeepTutor 仓库，也不会自动安装 NextChat、Codex CLI 或其他桌面 App。
