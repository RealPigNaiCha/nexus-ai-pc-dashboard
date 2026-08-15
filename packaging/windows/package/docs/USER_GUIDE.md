# Nexus AI-PC 简明使用说明

## 启动与停止

- 双击桌面的 `Nexus AI-PC` 快捷方式，或运行安装目录中的 `start-ai-pc.bat`。
- 浏览器访问地址：`http://127.0.0.1:8765`。
- 停止服务：运行安装目录中的 `stop-ai-pc.bat`。
- 验证安装：运行 `verify-installation.bat`。

服务只监听本机回环地址，局域网其他电脑不能访问。

## 第一次使用

1. 打开“设置”，选择模型服务商。
2. 保存 API 密钥。密钥进入 Windows Credential Manager，不写入数据库、日志或网页存储。
3. 为“深度推理”和“快速任务”配置模型角色并执行连接测试。
4. 把 PDF、Markdown 或 TXT 文件放入安装目录的 `data\library\original`，再到“资料库”主动导入。
5. 用一个资料中独有的词测试检索并核对来源、页码或段落。

没有 API 密钥时，资料导入、关键词检索、学习记录、科研项目和本地管理功能仍可使用；AI 生成和 PaperQA2 需要模型 API。DeepTutor 本次未随包提供。

## 数据位置

- 数据库：`data\database\ai-pc.sqlite3`
- 原始资料：`data\library\original`
- 解析缓存：`data\library\parsed`
- 向量索引与模型：`data\index`
- Obsidian 兼容笔记：`vault`
- 数据库备份：`backups\database`
- 日志：`logs`

建议定期备份 `data`、`vault` 和 `backups`。升级或换机前先停止服务，再复制这些目录。

## 常见问题

安装依赖失败：检查代理、防火墙、磁盘空间和系统时间，然后重新运行安装器。锁文件确保重复安装使用相同依赖版本。

网页打不开：运行 `verify-installation.bat`，再查看 `logs\dashboard.stderr.log`。端口 8765 被其他程序占用时，启动脚本会拒绝覆盖。

语义检索降级：通常是本地 BGE 模型未下载完成。关键词检索仍可用；网络恢复后重新运行安装包中的 `scripts\preload-model.py`，或再次执行安装器。

浏览器自动化不可用：重新执行安装目录虚拟环境中的 `python -m playwright install chromium`。
