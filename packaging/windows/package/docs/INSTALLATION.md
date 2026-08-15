# Nexus AI-PC 安装说明

## 最快安装

1. 将 ZIP 完整解压到普通文件夹，不要直接在压缩包预览窗口中运行。
2. 双击 `one-click-install.bat`。
3. 安装器默认部署到 `%LOCALAPPDATA%\Nexus-AI-PC`，自动安装 Python 3.12、锁定依赖、浏览器运行库和本地中文向量模型。
4. 安装结束后会执行健康检查并打开 `http://127.0.0.1:8765`。

安装依赖和模型需要联网，首次安装通常需要 10 到 30 分钟，取决于网络速度。至少预留 5 GiB 磁盘空间。程序仅支持 64 位 Windows 10/11。

## 未随包提供的可选工具

DeepTutor、NextChat、Codex CLI、Obsidian、Zotero、VS Code 和 Cline 均不是核心启动的必要条件，也不随本包安装。构建时的第三方依赖审计发现当前本机旧版 DeepTutor 与 NextChat 依赖树仍含待上游修复或升级的安全通告，因此本次朋友试用包只交付已通过审计的核心 Dashboard。

## 自定义目录

熟悉 PowerShell 的用户可以执行：

```powershell
.\scripts\install.ps1 -InstallRoot 'D:\Nexus-AI-PC'
```

路径可以包含空格。不要把安装目标直接设为磁盘根目录、用户主目录或 `%LOCALAPPDATA%` 本身。

## 更新与卸载

再次运行同版本或新版本安装器会更新程序文件，并保留 `data`、`vault` 和 `backups`。

安装目录内的 `uninstall-ai-pc.bat` 默认只移除程序与运行环境，保留用户数据。只有显式运行 `scripts\uninstall.ps1 -RemoveData` 才会删除数据目录。
