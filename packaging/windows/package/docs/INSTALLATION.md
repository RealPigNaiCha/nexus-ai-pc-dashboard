# Nexus AI-PC 安装说明

## 最快安装

1. 将 ZIP 完整解压到普通文件夹，不要直接在压缩包预览窗口中运行。
2. 双击 `one-click-install.bat`。
3. 安装器默认部署到 `%LOCALAPPDATA%\Nexus-AI-PC`，自动安装 Python 3.12、锁定依赖、浏览器运行库和本地中文向量模型。
4. 安装结束后会执行健康检查并打开 `http://127.0.0.1:8765`。

安装依赖、模型和 DeepTutor CLI 需要联网，首次安装通常需要 10 到 30 分钟，取决于网络速度。至少预留 8 GiB 磁盘空间。程序仅支持 64 位 Windows 10/11。

## 完整版安装要求与外部 App

完整版默认会安装 Dashboard 核心、Playwright Chromium、本地中文向量模型，以及 DeepTutor CLI v1.5.9。DeepTutor 来自官方仓库的固定提交 `37c3db6df7e886aee4f61c97ec5e618b8ab379e8`；安装器只在系统临时目录短暂检出源码，完成非 editable CLI 安装后立即删除源码，不会把第三方仓库复制进安装包。

自动部署 DeepTutor 前，请先手动安装 [Git for Windows](https://git-scm.com/download/win)，并重新打开 PowerShell 使 `git.exe` 出现在 PATH 中。若暂时只想安装 Dashboard 核心，可显式运行 `scripts\install.ps1 -SkipDeepTutor`；这不是完整版默认路径。

安装器不会静默安装需要用户登录、授权或独立更新的桌面 App。根据使用场景，从官方来源手动安装：

| App | 作用 | 是否必须 |
|---|---|---|
| [Git for Windows](https://git-scm.com/download/win) | 下载并部署 DeepTutor | 完整版必须 |
| [Codex CLI](https://developers.openai.com/codex/cli/) | 使用仓库中的 Codex 安装提示词 | 使用 Codex 自动安装时必须 |
| [Visual Studio Code](https://code.visualstudio.com/download) | 编程工作区 | 可选 |
| [Cline](https://marketplace.visualstudio.com/items?itemName=saoudrizwan.claude-dev) | VS Code Agent 执行器 | 可选 |
| [Obsidian](https://obsidian.md/download) | 编辑本地 `vault` | 可选 |
| [Zotero](https://www.zotero.org/download/) | 文献管理与只读同步 | 可选 |
| [Node.js LTS](https://nodejs.org/en/download/) | 运行 NextChat | 仅使用 NextChat 时需要 |
| [NextChat](https://github.com/ChatGPTNextWeb/NextChat) | 独立兼容对话界面 | 可选，需手动部署 |

NextChat 当前不由本安装包自动部署：Dashboard 已提供统一对话和 OpenAI 兼容接口，避免将另一个完整前端源码和依赖树固定进朋友安装包。需要 NextChat 时，请按其官方仓库说明单独安装。

## 使用 Codex 自动安装

已安装 Codex 的用户可以直接发送：

```text
按照 https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard 中的 prompts/install-with-codex.md 帮我安装
```

Codex 会读取仓库中的 [自动安装任务](https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard/blob/main/prompts/install-with-codex.md)，从当前 Release 下载 Windows 安装包和校验文件，验证文件大小及 SHA-256 后执行安装，并独立检查健康状态、数据目录、数据库完整性和回环地址绑定。执行过程中仍会遵守所在环境的权限确认与安全规则。

## 自定义目录

熟悉 PowerShell 的用户可以执行：

```powershell
.\scripts\install.ps1 -InstallRoot 'D:\Nexus-AI-PC'
```

路径可以包含空格。不要把安装目标直接设为磁盘根目录、用户主目录或 `%LOCALAPPDATA%` 本身。

## 更新与卸载

再次运行同版本或新版本安装器会更新程序文件，并保留 `data`、`vault` 和 `backups`。

安装目录内的 `uninstall-ai-pc.bat` 默认只移除程序与运行环境，保留用户数据。只有显式运行 `scripts\uninstall.ps1 -RemoveData` 才会删除数据目录。
