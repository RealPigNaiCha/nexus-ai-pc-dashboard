# 使用 Codex 安装 Nexus AI-PC

这是一份交给 Codex 执行的 Windows 安装任务。用户只需要发送：

```text
按照 https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard 中的 prompts/install-with-codex.md 帮我安装
```

## 给 Codex 的任务

在当前电脑上安装或更新 Nexus AI-PC Dashboard，并完成下载校验、安装验证和结果汇报。除非用户明确指定其他位置，否则安装到 `%LOCALAPPDATA%\Nexus-AI-PC`。

不要只给出操作教程，也不要要求用户手工执行你可以安全完成的步骤。持续工作到安装成功、得到明确失败结果，或遇到必须由用户处理的权限/登录问题。

## 安全边界

1. 仅支持 64 位 Windows 10/11。若当前系统不符合要求，停止安装并说明原因。
2. 只从 `https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard` 的 GitHub Release 下载文件，不使用镜像、网盘或第三方转载。
3. 安装正式发布的 Windows x64 ZIP，不要克隆开发源码代替安装包，也不要在源码目录中直接部署。
4. 必须同时下载对应的 `.sha256.txt` 文件，并在解压、运行脚本前使用 SHA-256 校验 ZIP。校验不一致时立即停止，不能绕过。
5. 不读取、打印、复制或上传 API 密钥、浏览器数据、Windows 凭据、个人资料库或其他私密文件。
6. 更新已有 Nexus AI-PC 时必须保留 `data`、`vault` 和 `backups`。不要使用带 `-RemoveData` 的卸载操作。
7. 如果目标目录非空但不是带 `.nexus-ai-pc-install.json` 标记的既有安装，停止并询问用户，不能覆盖。
8. 这是完整版安装流程：默认不要传 `-SkipDeepTutor`。DeepTutor 会由安装器从官方仓库的固定提交部署；不得把 DeepTutor 或 NextChat 的源码仓库复制进安装目录。
9. 不要静默安装需要用户登录、授权或独立更新的桌面 App。完成 Dashboard 安装后，向用户列出下方“需手动安装的 App”及官方链接；只有用户明确要求时才继续安装其中某个 App。
10. 遵守当前 Codex 环境的授权与安全规则。若执行已下载程序需要即时确认，应先完成所有只读检查，并在运行安装器前向用户说明具体操作。

## 安装步骤

### 1. 检查环境

- 确认操作系统为 64 位 Windows 10/11。
- 确认系统盘或用户指定的安装盘至少有 8 GiB 可用空间。
- 默认安装目录为 `%LOCALAPPDATA%\Nexus-AI-PC`。只有用户明确要求时才使用自定义目录。
- 自定义目录不能是磁盘根目录、用户主目录或 `%LOCALAPPDATA%` 本身。

### 2. 检查完整版前置条件

- 检查 `git.exe` 是否可用。若不可用，停止自动安装并提示用户先从 [Git for Windows](https://git-scm.com/download/win) 安装，重新打开 Codex 后再继续；不要用不明来源的 ZIP 或镜像替代 GitHub 官方仓库。
- 检查用户是否希望安装到默认目录；除非用户明确指定，否则使用 `%LOCALAPPDATA%\Nexus-AI-PC`。
- 告知用户：安装器会在临时目录检出 DeepTutor v1.5.9，验证提交 `37c3db6df7e886aee4f61c97ec5e618b8ab379e8`，完成 CLI 安装后删除临时源码；不会安装 DeepTutor 可选 Web Server 依赖。

### 3. 确定发布版本

- 读取仓库根目录 `README.md` 的“下载 Windows x64 完整版”链接，以 README 当前指向的 Release 标签和资产名为准，不要猜测版本号。
- 确认目标 Release 不是 Draft，并且同时包含以下两个匹配资产：
  - `Nexus-AI-PC-*-Windows-x64.zip`
  - `Nexus-AI-PC-*-Windows-x64.sha256.txt`
- 当前已验证版本为 `v0.9.0-dev.2-portable.2`；若 README 已指向更新版本，应以 README 和该 Release 附带的校验文件为准。

当前版本的 ZIP SHA-256 会在 Release 校验文件中提供；不要硬编码或猜测哈希：

```text
（以下载到的 `.sha256.txt` 为准）
```

如果 README 已指向更新版本，应使用 README 与该 Release 附带校验文件提供的新值，不要继续套用旧哈希。

### 4. 下载并校验

- 在系统临时目录下创建本次任务专用的随机子目录，不要把文件下载到仓库、安装目录或用户资料目录中。
- 通过 HTTPS 下载 ZIP 和对应的 SHA-256 文件。
- 读取校验文件中的文件名、版本、大小和 SHA-256；确认它描述的正是下载的 ZIP。
- 使用 PowerShell `Get-FileHash -Algorithm SHA256` 计算 ZIP 哈希，进行不区分大小写的完整字符串比较。
- 同时核对实际文件大小与校验文件记录的大小。任一检查失败都必须停止。

### 5. 解压并检查安装包

- 将 ZIP 解压到任务专用临时目录，不能直接从压缩包预览窗口运行。
- 防止 ZIP 路径穿越：所有解压目标必须仍位于该临时目录内。
- 找到解压后的单一包根目录，并确认至少存在：
  - `manifest.json`
  - `one-click-install.bat`
  - `一键安装.bat`
  - `scripts\install.ps1`
  - `scripts\verify.ps1`
  - `docs\INSTALLATION.md`
  - `docs\PRIVACY.md`
- 在执行前阅读 `docs\INSTALLATION.md` 和 `docs\PRIVACY.md`，检查实际要求是否与本任务一致。

### 6. 执行完整版安装

- 为避免批处理文件末尾的交互式 `pause` 阻塞自动化，从包根目录直接运行它所调用的 PowerShell 安装器：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\install.ps1"
```

- 用户指定自定义目录时，使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\install.ps1" -InstallRoot "D:\示例\Nexus-AI-PC"
```

- 安装过程会下载受管 Python 3.12、锁定的运行依赖、Chromium 运行库、本地中文向量模型，并从官方 DeepTutor 仓库安装 v1.5.9 CLI，通常需要 10–30 分钟。持续监控进程，不能因为暂时没有输出就提前结束任务。
- 只有用户明确要求核心-only 安装时才使用 `-SkipDeepTutor`；使用后必须在结果中明确说明 DeepTutor 未安装。
- 不要额外执行来源不明的脚本，不要修改系统级 Python，不要把依赖安装到全局环境。

### 7. 验证安装

安装器成功退出后，再独立运行一次安装目录中的验证脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Nexus-AI-PC\scripts\verify.ps1" -InstallRoot "$env:LOCALAPPDATA\Nexus-AI-PC" -StartIfNeeded
```

使用自定义目录时相应替换两处路径。只有以下检查全部通过才能报告安装成功：

- 受管 Python 环境可以运行。
- `http://127.0.0.1:8765/api/health` 返回 `status: ok`。
- 运行时数据根目录与实际安装目录一致。
- SQLite `PRAGMA quick_check` 返回 `ok`。
- 服务只监听本机回环地址，而不是局域网或公网地址。
- 若为完整版安装，`tools\deeptutor\.venv-cli\Scripts\python.exe` 存在，`.nexus-ai-pc-deeptutor.json` 的版本为 `1.5.9`，且 `import deeptutor_cli` 成功。

### 8. 完成与清理

- 安装成功后，可以删除本次任务创建的下载和解压临时目录；删除前再次确认它确实位于系统临时目录内且只属于本次任务。
- 不要删除安装目录、用户数据或已有备份。
- 向用户汇报：安装版本、安装目录、健康检查结果、Dashboard 地址和启动方式。
- 默认启动方式是桌面上的 `Nexus AI-PC` 快捷方式，或安装目录中的 `start-ai-pc.bat`。

## 需手动安装的 App

安装器不会静默安装桌面 App。请根据需要从官方来源下载：

- [Git for Windows](https://git-scm.com/download/win)：完整版自动部署 DeepTutor 的前置条件，安装前必须准备好。
- [Codex CLI](https://developers.openai.com/codex/cli/)：运行本提示词的推荐入口。
- [Visual Studio Code](https://code.visualstudio.com/download) + [Cline](https://marketplace.visualstudio.com/items?itemName=saoudrizwan.claude-dev)：编程 Agent 工作流。
- [Obsidian](https://obsidian.md/download)：打开 `vault` 知识库。
- [Zotero](https://www.zotero.org/download/)：文献管理与只读同步。
- [Node.js LTS](https://nodejs.org/en/download/) + [NextChat](https://github.com/ChatGPTNextWeb/NextChat)：仅在用户明确需要 NextChat 时手动部署；本提示词不自动克隆或构建 NextChat。

除 Git for Windows 外，这些 App 都不是 Dashboard 核心启动的硬性依赖。API 密钥、第三方登录和桌面 App 的最终授权由用户本人完成。

## 失败处理

- 明确指出失败发生在下载、校验、解压、依赖安装、启动还是健康检查阶段。
- 保留现有安装与用户数据，不要为“重试”而删除整个安装目录。
- 优先读取安装器输出；需要排错时只查看安装目录下 `logs\dashboard.stderr.log` 和 `logs\dashboard.stdout.log` 的相关末尾内容，并避免输出可能含有的隐私信息。
- 不要通过关闭校验、扩大执行权限、删除数据或改用非官方下载源来绕过错误。
