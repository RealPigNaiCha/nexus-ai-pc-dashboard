<div align="center">

# 🧠 Nexus AI-PC Dashboard

**把本地资料库、学习计划、科研检索和多模型 AI 协作收进一个只属于你的 Windows 工作台。**

[![Release](https://img.shields.io/badge/release-v0.9.0--dev.2--portable.1-7c3aed?style=for-the-badge)](https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard/releases/tag/v0.9.0-dev.2-portable.1)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?style=for-the-badge&logo=windows11&logoColor=white)](https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard/releases/tag/v0.9.0-dev.2-portable.1)

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-185%20passed-2ea44f?style=flat-square)](tests)
[![Coverage](https://img.shields.io/badge/coverage-81.69%25-2ea44f?style=flat-square)](tests)
[![Local first](https://img.shields.io/badge/privacy-local--first-f97316?style=flat-square)](packaging/windows/package/docs/PRIVACY.md)

### [⬇️ 下载 Windows x64 朋友试用版](https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard/releases/download/v0.9.0-dev.2-portable.1/Nexus-AI-PC-0.9.0.dev2-portable.1-Windows-x64.zip)

[查看版本说明](https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard/releases/tag/v0.9.0-dev.2-portable.1) · [下载安装说明](packaging/windows/package/docs/INSTALLATION.md) · [使用手册](packaging/windows/package/docs/USER_GUIDE.md) · [隐私说明](packaging/windows/package/docs/PRIVACY.md)

</div>

> [!IMPORTANT]
> 当前版本是面向朋友试用的 **预发布版本**。请勿直接在压缩包预览窗口中运行安装器；首次安装需要联网下载依赖和本地模型。

## 三步开始使用

1. 下载 [Windows ZIP 安装包](https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard/releases/download/v0.9.0-dev.2-portable.1/Nexus-AI-PC-0.9.0.dev2-portable.1-Windows-x64.zip) 和 [SHA-256 校验文件](https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard/releases/download/v0.9.0-dev.2-portable.1/Nexus-AI-PC-0.9.0.dev2-portable.1-Windows-x64.sha256.txt)。
2. 完整解压后，双击 `one-click-install.bat` 或 `一键安装.bat`。
3. 等待健康检查通过，浏览器会自动打开 `http://127.0.0.1:8765`。

默认安装目录为 `%LOCALAPPDATA%\Nexus-AI-PC`。支持 64 位 Windows 10/11，建议预留至少 5 GiB 磁盘空间；首次安装通常需要 10–30 分钟。

```text
SHA-256
49D3475D8D9F86C6BC7D0BD0233905A9008C47E6DEE999517CC23F56217D25F7
```

## 它能做什么

| 能力 | 当前实现 |
|---|---|
| 📚 本地资料库 | 导入 PDF、Markdown、TXT；支持扫描 PDF OCR、关键词/语义/混合检索和原页证据核对 |
| 💬 AI 对话 | 结合本地资料与学习状态回答问题，保留来源引用，并支持 fast / reasoning / auto 模型路由 |
| 🧭 学习管理 | 课程、知识点、答题证据、FSRS 复习队列、掌握度更新和可解释学习教练 |
| 🔬 科研工作流 | Crossref / OpenAlex 检索、筛选记录、证据表导出及 PaperQA2 论文问答 |
| 🔐 本地优先 | 服务仅监听 `127.0.0.1`；资料与索引保存在本机，API 密钥交由 Windows Credential Manager 保存 |
| 🛠️ 可维护性 | 在线 SQLite 备份、审计记录、用量预算、CLI / MCP / Codex 桥梁和可控浏览器动作 |

## 这次试用包包含什么

- Windows 一键安装、完整性校验、更新和卸载脚本。
- Dashboard 核心应用、锁定依赖、Python/uv 引导和本地中文向量模型预加载流程。
- 中文安装说明、用户手册、隐私说明及第三方许可清单。
- 已修复任意安装目录、新数据库初始设置缺失、启动脚本和工具路径写死等问题。

DeepTutor、NextChat、Codex CLI、Obsidian、Zotero、VS Code 和 Cline 不随本试用包安装，也不是核心 Dashboard 启动的必要条件。其中 DeepTutor 与 NextChat 因当前第三方依赖仍有待上游处理的安全通告，本次没有打包。

## 验证状态

- `185 passed`
- 测试覆盖率 `81.69%`
- Ruff、Pyright、Node 语法、锁文件与依赖一致性检查通过
- 核心运行环境已知漏洞审计结果为 `0`
- 安装包包含 104 个清单文件，隐私扫描通过

## 文档导航

| 文档 | 用途 |
|---|---|
| [安装说明](packaging/windows/package/docs/INSTALLATION.md) | 系统要求、最快安装、自定义目录、更新与卸载 |
| [用户手册](packaging/windows/package/docs/USER_GUIDE.md) | 首次启动、资料导入、模型配置和常见操作 |
| [隐私说明](packaging/windows/package/docs/PRIVACY.md) | 本地数据、联网边界、凭据与日志策略 |
| [第三方许可](packaging/windows/package/docs/THIRD_PARTY_NOTICES.md) | 随包组件与许可证信息 |
| [项目状态](PROJECT_STATUS.md) | 当前能力、安全边界和后续优先级 |
| [系统设计](DESIGN.md) | 模块边界、数据流、API 约定和开发接手说明 |
| [Windows 打包说明](packaging/windows/README.md) | 构建、验证和发布便携安装包 |

## 贡献者

<table>
  <tr>
    <td align="center" width="180">
      <a href="https://github.com/RealPigNaiCha">
        <img src="https://github.com/RealPigNaiCha.png?size=96" width="80" alt="RealPigNaiCha" /><br />
        <strong>@RealPigNaiCha</strong>
      </a>
    </td>
    <td>项目发起、产品方向、功能决策、实际使用反馈与发布。</td>
  </tr>
  <tr>
    <td align="center" width="180">
      <span aria-label="AI contributor">🤖</span><br />
      <strong>OpenAI Codex（GPT）</strong>
    </td>
    <td>代码检查、问题修复、测试验证、Windows 便携包、发布流程与文档整理。</td>
  </tr>
</table>

这个项目采用“人类负责目标与判断，AI 协助实现与验证”的协作方式。所有发布决定均由项目所有者确认。

## 本地开发

```powershell
git clone https://github.com/RealPigNaiCha/nexus-ai-pc-dashboard.git
Set-Location nexus-ai-pc-dashboard
uv sync --dev --locked
uv run pytest
uv run python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

项目要求 Python 3.12+。提交前请运行 Ruff、Pyright、pytest、Node 语法检查和 `git diff --check`；完整命令及开发环境说明见下方手册。

---

<details>
<summary><strong>展开：开发工作区的完整部署与运维手册</strong></summary>

> 下面记录开发工作区和可选集成的完整运维细节，其中部分路径与附加工具不属于便携试用包。普通试用者优先阅读上方安装说明与用户手册。

## Nexus AI-PC Dashboard 部署与运维手册

Nexus AI-PC Dashboard 是只监听本机回环地址的 FastAPI + SQLite 应用。当前可用的真实功能包括：本地 Dashboard、用户主动触发的 PDF/Markdown/TXT 导入、SQLite 词法检索、本地 BGE + Qdrant 语义/混合检索、FSRS 学习进度、可解释学习教练报告、自动复习调度执行器、Crossref/OpenAlex 科研检索、科研证据导出、PaperQA2、DeepTutor、统一多轮 AI 对话、隐私感知的主动联网查证、fast 整理 + reasoning 审阅的多模型协作、版本化任务信封与结果回写、Codex/CLI/MCP 桥梁、受控改进提案、用量与预算、Zotero 只读同步、VS Code + Cline 显式交接、Windows 凭据库、在线备份和审计。电脑控制尚未接入 Windows 执行器。新建数据库保持为空，不会自动生成虚构活动。

项目当前状态、安全边界和后续优先级见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。下次继续开发时应先阅读该文件，复用现有数据底座。

扫描 PDF 的候选项目、许可证、真实样书基线与选型理由见 [OCR_EVALUATION.md](OCR_EVALUATION.md)。

模块边界、数据流、API 约定和接手流程见 [DESIGN.md](DESIGN.md)。涉及结构迁移、模型调用或电脑自动化前，应先阅读该设计说明。

产品方向是“图书馆 + 调度中心”：资料、实验和学习证据长期沉淀在本地，Dashboard 连接 Codex、CLI、skills、MCP 和多种模型，但不要求用户放弃更成熟的执行器，也不把长期知识绑定到单一聊天窗口。

普通用户的日常使用说明见 [便携版用户手册](packaging/windows/package/docs/USER_GUIDE.md)：包含首次启动、页面导览、模型配置、资料导入和常见问题。

正式部署目录为 `C:\AI-PC\app\dashboard`，访问地址为 `http://127.0.0.1:8765`。直接双击 `index.html` 只会进入演示模式，不能访问本地数据库或导入文件。

## 1. 当前目录布局

```text
C:\AI-PC\
  app\dashboard\                 # 前端、FastAPI 后端、脚本和项目虚拟环境
  data\database\ai-pc.sqlite3    # 业务数据与 FTS5 全文索引
  data\library\original\        # 推荐放 PDF、Markdown、TXT 原始资料
  data\library\parsed\          # 后续复杂解析结果
  data\index\qdrant\            # 嵌入式 Qdrant 向量索引
  data\index\models\            # BAAI/bge-small-zh-v1.5 模型缓存
  data\index\paperqa\           # PaperQA2 论文索引（向量 + 文档快照）
  data\zotero\                   # Zotero 数据库与附件
  tools\nodejs\                  # Node.js LTS，用于前端语法检查和后续工具链
  vault\                         # Obsidian Markdown Vault，也是允许导入目录
  backups\database\              # SQLite 备份
  logs\dashboard.stdout.log      # 后台服务标准输出
  logs\dashboard.stderr.log      # 后台服务错误日志
```

数据库默认路径是 `C:\AI-PC\data\database\ai-pc.sqlite3`。`run.ps1` 会按项目位置计算该路径，也可通过进程级环境变量 `AI_PC_DB_PATH` 覆盖。当前资料导入白名单仍固定为 `C:\AI-PC\data\library` 和 `C:\AI-PC\vault`；Dashboard 设置页中的“数据目录”暂时只是业务设置，不能改变导入白名单。

## 2. 软件前提

- Windows 10/11 64 位。
- 项目已有 `.venv` 时可直接运行，不要求全局 Python。
- 更新依赖时建议安装 `uv`，并在项目目录执行 `uv sync --dev`。
- Git for Windows、Obsidian、Zotero 已安装。Obsidian Vault 为 `C:\AI-PC\vault`，Zotero 数据目录为 `C:\AI-PC\data\zotero`。
- Node.js LTS 安装在 `C:\AI-PC\tools\nodejs`，不是 Dashboard 运行时必需依赖。
- 当前阶段不安装 Docker Desktop、WSL2、Dify 或 n8n。

首次部署或依赖发生变化时：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
uv sync --dev
```

默认环境只安装 Dashboard 正式功能和开发检查工具。JupyterLab、Pandas、Polars、SciPy 等实验分析工具属于可选 `lab` 组，需要时在开发工作区执行 `uv sync --dev --group lab`；正式服务不依赖该组。

`uv` 已安装在 `%USERPROFILE%\.local\bin`，该目录也已写入用户 PATH。安装前已经打开的终端可能仍找不到命令，关闭后重新打开 PowerShell 即可。Dashboard 的启动脚本也会自动回退到 `.venv\Scripts\python.exe`；不要手工把包安装到系统 Python。

## 3. 启动、停止与检查

在 PowerShell 中运行：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\start.ps1
```

`start.ps1` 会在后台启动服务、等待健康检查通过，然后打开浏览器。首次冷启动需要加载本地向量模型，可能耗时数十秒；脚本最多等待 120 秒，端口被占用但健康检查未通过时会给出明确提示。只启动服务、不打开浏览器：

```powershell
.\start.ps1 -NoBrowser
```

停止服务：

```powershell
.\stop.ps1
```

检查健康状态：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/health'
Invoke-RestMethod 'http://127.0.0.1:8765/api/overview'
```

常用地址：

- Dashboard：`http://127.0.0.1:8765`
- API 文档：`http://127.0.0.1:8765/api/docs`
- OpenAPI：`http://127.0.0.1:8765/api/openapi.json`

服务只绑定 `127.0.0.1:8765`，局域网中的其他电脑无法直接访问。`stop.ps1` 只会停止命令行中包含 `uvicorn backend.app:app` 的监听进程；如果 8765 端口属于其他程序，它会拒绝终止。

## 4. PDF、Markdown 和 TXT 导入

### 允许目录

后端只允许读取以下两个根目录及其子目录：

1. `C:\AI-PC\data\library`
2. `C:\AI-PC\vault`

推荐把书籍和论文放到 `C:\AI-PC\data\library\original`，Obsidian 笔记保留在 `C:\AI-PC\vault`。导入白名单以解析后的真实路径判断，不能通过 `..` 或指向目录外的链接绕过。其他位置会返回 HTTP 403；先把文件移入允许目录，再执行导入。

### 支持格式和限制

| 项目 | 当前规则 |
|---|---|
| PDF | `.pdf`；优先提取原生文本层，扫描页自动使用本地 RapidOCR，并保留页码、置信度和证据坐标 |
| Markdown | `.md`、`.markdown` |
| 纯文本 | `.txt`，支持 UTF-8、UTF-8 BOM 和 GB18030 |
| 单文件大小 | 最大 512 MiB；超过即拒绝 |
| 目录导入 | 递归扫描，单次最多 500 个受支持文件 |
| 暂不支持 | DOCX、EPUB、图片、音视频及其他扩展名 |

扫描版和混合型 PDF 会逐页判断文本层质量，只对缺少可用文本的页面运行本地 RapidOCR（ONNX Runtime CPU）。原 PDF 始终保持只读；OCR 页面图像、逐区域文本、置信度、坐标、图片哈希和引擎版本保存在 `C:\AI-PC\data\library\parsed\<哈希前缀>\<文件 SHA-256>`。派生目录可重建，不能替代原文件备份。

首次处理扫描书通常需要数秒/页。每页完成后立即原子保存缓存，任务中断后重新导入会复用已验证的页面，不必从第一页开始。资料库检索结果中的页码可打开原 PDF 页面并高亮命中区域；这用于人工或视觉模型复核，不表示 OCR 文本一定正确。公式、上下标和密集表格尤其应查看原页。

真实 324 页扫描教材验收中，323 页 OCR、1 页原生文本、0 页不可读，共生成 2227 个检索片段；首次处理约 29 分 27 秒，第二次完整缓存复用约 25 秒，派生证据约 94.28 MiB。区域平均置信度约 95.43%，但公式和表格仍需回到原页复核。详细数据和候选项目比较见 [OCR_EVALUATION.md](OCR_EVALUATION.md)。

OCR 状态与证据图像接口：

```text
GET /api/library/ocr/status
GET /api/library/ocr/progress?path=<允许目录内的文件或目录>
GET /api/library/documents/{document_id}/pages/{page_number}/image
```

### 从网页导入

1. 启动 Dashboard，进入“资料库”。
2. 在“文件或文件夹路径”中输入允许目录内的绝对路径。
3. 点击“导入并索引”。文件夹会递归处理；不支持的扩展名会跳过。
4. 完成后用一个只存在于该资料中的词测试检索，并核对来源路径、PDF 页码或文本段落号。

也可以直接调用 API：

```powershell
$payload = @{ path = 'C:\AI-PC\data\library\original' } | ConvertTo-Json
$body = [System.Text.Encoding]::UTF8.GetBytes($payload)
Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8765/api/library/import' `
  -Method Post `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body
```

单文件成功会返回文档、片段数和 `changed`。目录导入还会返回扫描数、更新数、复用数、失败数和逐文件错误。目录中个别文件解析失败时，其余文件仍可成功导入；如果没有任何文件成功，接口返回 HTTP 422。

### 增量与去重

- 每个文件按 SHA-256 内容哈希去重。
- 同一路径且内容未变化时直接复用，不重建片段。
- 同一路径内容变化时，旧片段会在同一数据库事务中替换。
- 不同路径但内容完全相同只保留一份索引。
- 解析版本变化时会重建派生片段；相同版本复用按文件哈希保存的 OCR 页面缓存。
- 原生文本按段落切分；OCR 文字按页面阅读顺序合并为较短片段，超长内容继续拆到最多约 1800 字符；两者都保留页码和证据区域。

## 5. 词法、语义与混合检索

资料内容保存在 SQLite，全文索引使用 FTS5 的 `unicode61` tokenizer：

- 英文等适合分词、长度至少 3 的查询使用 FTS5，并按 BM25 排序。
- 中文词组和少于 3 个字符的短词自动使用 `LIKE` 子串检索，因此“极限”“连续”可直接搜索。
- 多个查询词使用 AND 语义，即同一片段必须同时包含全部词。
- 网页每次显示最多 20 条；API 的 `limit` 可设为 1 至 100，查询最长 500 字符。
- 返回结果包含标题、来源路径、类型、页码、段落号、片段序号、高亮摘要、文本来源、OCR 置信度和证据坐标；扫描页可直接打开原页核验。

本机还启用了 `BAAI/bge-small-zh-v1.5`（512 维）和嵌入式 Qdrant。模型只做本地文本向量，不是本地大语言模型，资料片段不会发送到外部 embedding 服务。网页可切换：

- `混合`：默认模式，使用 Reciprocal Rank Fusion 合并词法与语义排名。
- `语义`：适合同义表达、自然语言问题和概念相近内容。
- `关键词`：只使用 SQLite FTS5/子串检索，结果最容易精确复核。

文档内容变化时会增量替换该文档的向量。语义组件不可用时接口自动退回 SQLite，并在页面显示“SQLite 回退”；词法检索始终保留。

API 示例：

```powershell
$query = [Uri]::EscapeDataString('数列 极限')
Invoke-RestMethod "http://127.0.0.1:8765/api/library/search?q=$query&limit=20"
```

语义索引状态与重建：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/library/semantic/status'
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/library/semantic/rebuild' -Method Post
```

文档和向量计数以 `/api/overview` 与 `/api/library/semantic/status` 的实时结果为准。2026-08-08 最近一次正式验收为 19 篇文档、271 个向量点；重建失败时不影响 SQLite 关键词检索。

### 5.1 学习进度

- 课程包含目标和可选目标日期。
- 知识点可记录描述和同课程前置关系。
- 每次答题可保存题目、答案、反馈、得分、信心、用时和提示次数。
- FSRS 根据证据生成 Again/Hard/Good/Easy 评级和下一次到期时间。
- 掌握度采用有界证据更新，低分会降低掌握度，提示次数会降低本次证据权重。
- 学习页“开始复习”按钮会按“到期复习 → 新知识点 → 薄弱前置”生成队列（`GET /api/learning/review/queue`），逐项自动带入题目提示并保存答题；完成一项后自动进入下一项。

### 5.2 科研检索

- 每个科研项目保存研究问题、类型、检索运行、候选论文、筛选决定和研究日志。
- 检索同时请求 Crossref 与 OpenAlex，使用明确超时和 `Nexus-AI-PC/0.1` User-Agent。
- DOI 会规范化并跨来源去重；来源元数据、作者、摘要、引用数和 URL 会合并。
- 只有两个来源都成功后才在单个 SQLite 事务中保存，网络或上游错误不会留下半份检索记录。
- 公共元数据接口不需要用户 API 密钥；论文全文解析和扫描件 OCR 尚未接入。
- 科研页“可追溯性”面板可一键导出证据表：`GET /api/research/projects/{id}/export` 生成 Markdown，包含研究问题、可复现检索式与来源、证据表、筛选汇总和研究日志，导出动作写入审计，不包含任何密钥。

### 5.3 PaperQA2 论文问答

- 科研页提供“PaperQA2 论文问答”区域：填写 `C:\AI-PC\data\library` 或 `C:\AI-PC\vault` 内的文件/目录路径，点击“建立索引”。
- 索引在本地生成：解析 PDF / Markdown / TXT，用本地 BGE 模型（`BAAI/bge-small-zh-v1.5`）向量化，并保存为 `C:\AI-PC\data\index\paperqa\docs.pkl` + `manifest.json` 快照；原文件只读。
- 提问复用现有“深度推理 / 快速任务”模型角色：服务在调用瞬间从 Windows Credential Manager 读取密钥，在进程内构造 LiteLLM Router，不写任何长期配置文件。
- `POST /api/paperqa/ask` 返回 `answer`、`formatted_answer`、`context`、`references` 和 `sources`（含引用与证据片段）；`model_calls` 记录服务商、模型、角色、耗时和 token，不保存论文全文提示词。
- 依赖说明：`paper-qa==5.29.1` 与 `paper-qa-pypdf==5.29.1` 必须成对锁定（新版 `2026.x` 的 pypdf 解析器与 5.29 不兼容）。

### 5.4 DeepTutor 教学与研究问答

DeepTutor 是独立安装的教学能力执行器（当前 v1.5.9），通过 Dashboard 的适配器调用，不运行交互式 `deeptutor init` 向导：

- `GET /api/deeptutor/status`：报告安装状态、版本、工作区和 `reasoning` / `fast` 模型角色是否可用（只返回配置状态，不返回密钥）。
- `POST /api/deeptutor/run`：一次调用一个能力，支持 `chat`（自由对话）、`deep_solve`（深度解题）、`deep_question`（生成题目）和 `deep_research`（深度研究）；语言支持 `zh` / `en`。
- 模型角色复用设置页的 `reasoning` / `fast` 角色；密钥从 Windows Credential Manager 按调用读取。
- 密钥只在单次 CLI 子进程运行期间写入 `C:\AI-PC\data\deeptutor\data\user\settings\model_catalog.json`，调用结束后立即还原无密钥基线；密钥不进入参数、日志、SQLite、审计或持久化配置。
- 每次调用写入 `model_calls`（服务商、模型、角色、耗时、token、错误码）和 `audit_events`；提示词正文不记录。
- 工作区首次使用时自动初始化非敏感默认设置；不创建长期密钥配置。
- DeepTutor 的 `.venv-cli` 已补充 `deeptutor run` 需要的 server 依赖（fastapi、uvicorn、pocketbase 等）；换机器或重建环境后需要重新安装。

PowerShell 调用示例：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/deeptutor/status'

$payload = @{
  capability = 'deep_solve'
  prompt     = '请解释数列极限的 ε-N 定义，并给出一道例题'
  role       = 'reasoning'
  language   = 'zh'
} | ConvertTo-Json
$body = [System.Text.Encoding]::UTF8.GetBytes($payload)
Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8765/api/deeptutor/run' `
  -Method Post `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body
```

返回包含 `answer`、`session_id`、`turn_id`、`model`、`latency_ms` 和 token 统计。首次运行会初始化工作区，之后单次调用通常在数十秒内完成；`deep_research` 可能更久，API 超时上限为 600 秒。

### 5.5 AI 对话（统一问答）

侧边栏“AI 对话”页是适合快速入门的统一问答入口：输入问题后，系统先检索本地资料和学习进度，再调用模型生成带 `[1]`、`[2]` 编号引用的回答；每次回答下方可展开“来源”核对原文路径、页码/段落和片段，“学习进度”折叠区显示待复习与薄弱前置。

- `POST /api/chat/ask`：请求体为 `{question, role, scope, course_id?, web_search?}`；`role` 支持 `reasoning` / `fast` / `auto`，`scope` 为 `all`、`library` 或 `learning`；`web_search` 支持 `auto`（默认）、`on`、`off`。自动模式只对时效/查证型问题触发，并阻止疑似本机路径、邮箱、令牌和手机号外发。
- 检索结果与学习状态只在调用瞬间拼入提示词；回答返回 `answer`、`evidence`、`learning_state`、`semantic_degraded`、模型信息与 token 统计。
- 自然语言长句在词法检索无结果时，会按中文关键词自动回退检索；语义索引不可用时与现有检索一致地降级到 SQLite。
- 提示词要求证据分级：区分【资料原文】【资料推断】【模型知识】【推测】；高影响结论标注【需验证】并建议第二来源或人工复核；用户观点有误时给出反例或边界条件，而不是迎合用户。
- 模型角色未配置时返回 `409`，`model_calls` 记录 `chat/error/role_not_configured`，审计事件正常；回答、提示词和密钥都不会持久化。

PowerShell 调用示例：

```powershell
$payload = @{
  question = '数列极限的 ε-N 定义是什么？'
  role     = 'reasoning'
  scope    = 'all'
} | ConvertTo-Json
$body = [System.Text.Encoding]::UTF8.GetBytes($payload)
Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8765/api/chat/ask' `
  -Method Post `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body
```

### 5.6 多轮对话（已合并进 AI 对话页）

“多轮对话”已经合并进侧边栏原有的“AI 对话”页，界面与 Dashboard 完全一致：同一个气泡样式、来源核对、学习进度和会话小计。页面顶部提供“新建对话”按钮，每次提问会携带完整历史记录走 `POST /v1/chat/completions`（OpenAI 兼容、支持 `scope`），并按会话记录用量。

同时保留了可选的 [NextChat](https://github.com/ChatGPTNextWeb/NextChat)（MIT License）独立服务：`http://127.0.0.1:3000` 仍可访问，适合需要更丰富设置的场景，但不再作为 Dashboard 的独立导航入口。模型密钥仍只在本机服务调用瞬间从 Windows Credential Manager 读取。

快速启动（可选）：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\start.ps1 -WithChat         # Dashboard + 可选 NextChat
.\stop-nextchat.ps1           # 停止可选 NextChat
```

后端保留的兼容接口：

- `GET /v1/models`：返回当前可用的 `reasoning` / `fast` 角色与实际模型名。
- `POST /v1/chat/completions`：接受标准 `messages[]`、`model`、`stream`、`max_tokens`、`temperature`；支持流式 SSE。最近一条用户消息会先检索本地资料与学习进度，多轮历史拼入提示词，回答末尾附带本地资料引用列表。

每次调用写入 `model_calls`（operation=`openai_compat_chat`、source=`nextchat`）与审计（`chat/openai_completions`）。NextChat 源码与构建产物位于 `C:\AI-PC\tools\nextchat`，正式环境需要 Node.js LTS；当前部署脚本会优先使用系统 `node`，找不到时回退到 Codex 自带运行时。

### 5.7 用量小计与月度预算

侧边栏“用量”页汇总本月模型调用：成功次数、Prompt/Completion/总 Token、按来源（操作）统计和按 NextChat 会话的小计。模型密钥仍不进入统计；成本按常见公开价目表估算，未知模型使用通用费率。

设置月度预算后，`/api/chat/ask`、`/v1/chat/completions`、`/api/collaboration/run`、`/api/models/generate`、`/api/paperqa/ask` 和 `/api/deeptutor/run` 在预算用尽后会返回 `429 Monthly model budget exceeded` 并写入审计。预算为 0 表示不限制。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/usage'
$body = @{ monthly_budget_usd = 5.0 } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/usage/budget' -Method Put -ContentType 'application/json' -Body $body
```

### 5.8 手动资料导入

资料库不会在后台定时扫描磁盘。用户在资料库页输入允许目录内的文件或文件夹路径并点击“导入并索引”后，系统才会读取 PDF / Markdown / TXT、更新词法与语义索引；相同内容的文件直接复用，不会重复建索引。接口为：

- `POST /api/library/import`（`{path}`）

### 5.9 复习提醒角标

学习页已有“到期复习”列表；现在侧边栏“学习”入口会显示待复习数量角标，服务不可用或没有到期项时自动隐藏。

### 5.10 模型路由（auto）

统一 AI 对话、兼容对话、PaperQA2、DeepTutor 和最小生成调用的角色都支持 `auto`：显式指定 `reasoning` / `fast` 时始终优先；`auto` 会按问题复杂度（分析、比较、证明、评估等关键词、长度与多问句）选择深度推理或快速任务。设置页“模型路由（auto）”可逐任务固定模式，或开启“低预算优先”——月度预算剩余不足 25% 时自动改用快速任务。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/routing/rules'
$body = @{ mode = 'auto'; prefer_low_cost = $true } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/routing/rules/chat' -Method Put -ContentType 'application/json; charset=utf-8' -Body $body
```

### 5.11 Zotero 附件导入资料库

Zotero 只读同步后，设置页可点击“导入附件到资料库”：`POST /api/zotero/import-attachments` 只接受 Zotero 快照记录且物理位于 `C:\AI-PC\data\zotero` 内的 PDF / Markdown / TXT，使用与资料库相同的哈希去重、FTS5 与本地语义索引管道，并写入审计。位于数据目录之外的附件会被忽略。

## 6. API 密钥与 Windows Credential Manager

密钥接口已经接入 Windows Credential Manager，并验证使用 `keyring.backends.Windows.WinVaultKeyring`。密钥服务名固定为 `Nexus AI-PC API Credentials v1`，支持以下规范服务商 ID：

```text
openai
openai-compatible
anthropic
google-gemini
deepseek
alibaba-bailian
```

接口只返回 `configured: true/false`，不会读回或显示密钥；SQLite 和审计日志只记录服务商及操作，不保存密钥。普通 `/api/settings` 接口仍会拒绝 `api_key` 字段。

日常配置直接使用 Dashboard 的“设置”页：左侧服务商列表会同时显示六个服务商的凭据状态与角色用途，右侧只编辑当前服务商的地址和密钥，下方角色路由表集中维护模型 ID。粘贴密钥并保存后输入框会立即清空，刷新页面也只读取 `configured` 状态，不会回显密钥。下列 PowerShell 接口主要用于验收和删除凭据。

查看配置状态：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/credentials'
Invoke-RestMethod 'http://127.0.0.1:8765/api/credentials/openai'
```

写入密钥时不要把明文直接写进脚本文件或命令历史：

```powershell
$secureKey = Read-Host '输入 API 密钥' -AsSecureString
$credential = [PSCredential]::new('api-key', $secureKey)
$payload = @{ api_key = $credential.GetNetworkCredential().Password } | ConvertTo-Json
$body = [System.Text.Encoding]::UTF8.GetBytes($payload)
Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8765/api/credentials/openai' `
  -Method Put `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body
Remove-Variable secureKey, credential, payload, body
```

删除某服务商的密钥：

```powershell
Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8765/api/credentials/openai' `
  -Method Delete
```

设置页可通过 `POST /api/models/test` 发起只读连接测试。后端会先校验服务商与端点，再在调用瞬间从 Windows Credential Manager 读取密钥，请求模型列表端点后立即丢弃内存引用。接口只返回服务商、状态和耗时；`model_calls` 只记录操作、来源、耗时、状态和错误码，不保存密钥、响应正文或模型列表。

OpenAI、Anthropic、Google Gemini、DeepSeek 和阿里云百炼只能连接各自的官方 HTTPS 域名；兼容 OpenAI 的服务必须使用 HTTPS，本机回环地址例外。连接测试会区分未配置、鉴权失败、限流、超时、网络错误和上游错误。它仅验证端点与凭据，不会生成对话内容，也不代表模型路由已经配置完成。

## 7. 数据库备份与恢复

SQLite 使用 WAL 模式。服务运行时不要只复制 `ai-pc.sqlite3` 主文件，否则可能遗漏仍在 `-wal` 文件中的事务。

### 方法 A：在线一致性备份（推荐）

此方法调用 SQLite 原生 backup API，服务可以继续运行：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$sourceDb = 'C:\AI-PC\data\database\ai-pc.sqlite3'
$backupDir = 'C:\AI-PC\backups\database'
$backupDb = Join-Path $backupDir "ai-pc-$stamp.sqlite3"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
& '.\.venv\Scripts\python.exe' -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $sourceDb $backupDb
& '.\.venv\Scripts\python.exe' -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA quick_check').fetchone()[0]); c.close()" $backupDb
```

最后一条命令应输出 `ok`。

### 方法 B：停服复制

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\stop.ps1
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item 'C:\AI-PC\data\database\ai-pc.sqlite3' "C:\AI-PC\backups\database\ai-pc-$stamp.sqlite3"
.\start.ps1 -NoBrowser
```

完整备份还应包含 `C:\AI-PC\data\library` 和 `C:\AI-PC\vault`。数据库保存的是索引和状态，不包含原始 PDF 的副本；API 密钥也不应存入数据库。

### 自动备份与保留策略

Dashboard 服务运行期间会按设置自动执行在线一致性备份。设置页“备份与磁盘”区域可配置：

| 设置 | 默认 | 范围 | 说明 |
|---|---|---|---|
| 启用自动备份 | 开启 | 开/关 | 关闭后仅保留手动“立即备份” |
| 备份间隔 | 24 小时 | 1–720 小时 | 从上一次启动间隔起算，每次循环重新读取设置 |
| 保留份数 | 14 份 | 1–365 份 | 超过保留份数的 `ai-pc-*.sqlite3` 会被清理并写入审计 |

设置通过 SQLite `settings` 表持久化，也可直接调用 API：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/ops/backup/settings'

$payload = @{ enabled = $true; interval_hours = 24; keep_count = 14 } | ConvertTo-Json
$body = [System.Text.Encoding]::UTF8.GetBytes($payload)
Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8765/api/ops/backup/settings' `
  -Method Put `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body
```

保留策略只作用于 `C:\AI-PC\backups\database` 下匹配 `ai-pc-*.sqlite3` 的文件；手动备份和自动备份都按同一规则计数。删除前会再次解析真实路径，确保不会跟随符号链接删除目录外的文件。

### 恢复数据库

恢复会替换当前业务状态，先停止服务并给现库留一份回退副本：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\stop.ps1
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$database = 'C:\AI-PC\data\database\ai-pc.sqlite3'
$backup = 'C:\AI-PC\backups\database\ai-pc-YYYYMMDD-HHMMSS.sqlite3' # 改为实际文件
Copy-Item $database "C:\AI-PC\backups\database\ai-pc-before-restore-$stamp.sqlite3"
foreach ($suffix in @('-wal', '-shm')) {
  $sidecar = "$database$suffix"
  if (Test-Path -LiteralPath $sidecar) {
    Move-Item -LiteralPath $sidecar -Destination "$sidecar.before-restore-$stamp"
  }
}
Copy-Item -LiteralPath $backup -Destination $database -Force
.\start.ps1 -NoBrowser
Invoke-RestMethod 'http://127.0.0.1:8765/api/health'
```

启动时会执行向前兼容的数据库迁移。不要用新版数据库去覆盖旧版应用；需要回退应用时应同时回退匹配的数据库备份。

## 8. 点击启动与日志

日常启动直接双击：

```text
C:\AI-PC\start-ai-pc.bat
```

或双击中文名版本 `C:\AI-PC\启动AI-PC.bat`。脚本会启动本地服务并自动打开 Dashboard。

命令行方式：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\start.ps1
```

默认不再使用开机自启。如果确实需要登录自启动，可手动安装（可选）：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\install-startup.ps1 -Install
```

停用自启动（不会删除应用或数据）：

```powershell
.\install-startup.ps1
```

排错时查看：

```powershell
Get-Content 'C:\AI-PC\logs\dashboard.stderr.log' -Tail 100
Get-Content 'C:\AI-PC\logs\dashboard.stdout.log' -Tail 100
```

## 9. 迁移到新硬盘

系统盘已升级为 512 GB SSD，并继续作为 Windows 的 `C:` 盘，因此应用路径未变化。2026-08-06 最终复测 NTFS 卷总容量约 511.4 GB、可用约 448.3 GB。可用空间会随 Windows 临时文件和缓存波动；后续仍需按正常运维流程复测健康检查、资料计数、中文检索和完整测试。

下面的目录联接方案只适用于“不克隆 Windows，只把 `C:\AI-PC` 单独搬到另一个盘符”的情况。

当前代码的导入白名单使用 `C:\AI-PC`，因此最稳妥的无代码迁移方式是把数据搬到新 SSD，同时用 NTFS 目录联接保留逻辑路径 `C:\AI-PC`。新盘应使用固定盘符和 NTFS；不要使用当前的小容量 FAT32 安装介质。

1. 停止 Dashboard，并创建数据库和资料备份。
2. 在新 SSD 建立例如 `E:\AI-PC` 的空目录。
3. 使用下面的命令复制；`robocopy` 返回码 0 至 7 通常表示成功或存在可接受差异，8 以上表示失败。

```powershell
& 'C:\AI-PC\app\dashboard\stop.ps1'
New-Item -ItemType Directory -Path 'E:\AI-PC' -Force | Out-Null
robocopy 'C:\AI-PC' 'E:\AI-PC' /E /COPY:DAT /DCOPY:DAT /XJ /R:2 /W:2
```

4. 比较关键目录和数据库校验结果。确认复制完成后，把原目录重命名为回退副本，再创建联接：

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Set-Location 'C:\'
Rename-Item -LiteralPath 'C:\AI-PC' -NewName "AI-PC.before-move-$stamp"
New-Item -ItemType Junction -Path 'C:\AI-PC' -Target 'E:\AI-PC'
```

5. 重新启动并验收健康检查、资料数量、中文检索和测试。至少保留原目录到一次完整备份和重启验证完成后。

如果希望彻底改用 `E:\AI-PC` 而不保留联接，需要同时调整导入白名单和部署配置，属于下一次代码变更，不要只改 Dashboard 设置页的路径。

## 10. 测试与验收命令

完整质量检查应在 Git 工作区执行：

```powershell
Set-Location 'C:\AI-PC\workspaces\ai-pc-dashboard'
uv sync --dev --locked
uv run ruff check backend tests
uv run pyright
uv run pytest --cov=backend --cov-report=term-missing --cov-fail-under=80
& 'C:\AI-PC\tools\nodejs\node.exe' --check app.js
git diff --check
```

安装前已经打开的终端暂时找不到 `uv` 时，使用已有项目环境：

```powershell
& '.\.venv\Scripts\python.exe' -m pytest
```

只验证资料导入、去重、PDF 页码、中文检索、路径白名单和数据库迁移：

```powershell
& '.\.venv\Scripts\python.exe' -m pytest 'tests\test_library.py' -q
```

验证正式数据库完整性：

```powershell
& '.\.venv\Scripts\python.exe' -c "import sqlite3; c=sqlite3.connect(r'C:\AI-PC\data\database\ai-pc.sqlite3'); print(c.execute('PRAGMA quick_check').fetchone()[0]); c.close()"
```

2026-08-08 工作区 `0.7.0.dev1` 完整验收为 `160 passed`、总覆盖率 `82.05%`；Ruff、增量 Pyright、前端语法和 `git diff --check` 均通过。真实扫描教材已完成整书 OCR、缓存复用、词法/语义/混合检索与桌面/移动证据高亮验收。

## 11. 常见问题

| 现象 | 处理 |
|---|---|
| 页面显示“演示模式” | 不要直接打开 HTML；运行 `start.ps1` 后访问 `http://127.0.0.1:8765` |
| 启动失败 | 查看 `C:\AI-PC\logs\dashboard.stderr.log`；确认 8765 端口未被其他程序占用 |
| 导入返回 403 | 路径不在两个允许根目录中，先移动资料 |
| 导入返回 400 | 文件类型不支持、路径不是文件/目录，或目录没有支持的文件 |
| 导入返回 422 | 所有候选文件均解析失败；通过 API 文档查看错误详情 |
| 扫描 PDF 搜不到 | 查看 `/api/library/ocr/status`，确认 OCR 已启用且 RapidOCR 可用；首次处理大书需要数秒/页 |
| 中文结果太多 | 使用更长词组或增加第二个限定词 |
| `uv` 命令不存在 | 关闭后重开 PowerShell；仍不可用时检查用户 PATH 是否包含 `%USERPROFILE%\.local\bin`，已部署环境也可直接用 `.venv\Scripts\python.exe` |

## 12. 当前 API

- `/api/health`、`/api/overview`
- `/api/library/documents`、`/api/library/import`、`/api/library/search`
- `/api/library/semantic/status`、`/api/library/semantic/rebuild`
- `/api/learning/courses`、`/api/learning/concepts`、`/api/learning/dashboard`
- `/api/learning/progress`、`/api/learning/attempts`
- `/api/learning/review/queue`
- `/api/research/projects`、`/api/research/projects/{id}/notes`
- `/api/research/projects/{id}/searches`、`/api/research/searches/{id}`
- `/api/research/projects/{id}/screening`、`/api/research/projects/{id}/papers/{paper_id}/screening`
- `/api/research/projects/{id}/export`
- `/api/paperqa/status`、`/api/paperqa/index`、`/api/paperqa/ask`
- `/api/deeptutor/status`、`/api/deeptutor/run`
- `/api/chat/ask`
- `/api/collaboration/run`
- `/v1/chat/completions`、`/v1/models`
- `/api/usage`、`/api/usage/budget`
- `/api/tools`、`/api/agent/status`
- `/api/agent/tasks`、`/api/agent/tasks/{id}/progress`、`/api/agent/tasks/{id}/handoff`
- `/api/bridge/tasks/{id}/envelope`、`/api/bridge/tasks/{id}/results`
- `/api/improvements/signals`、`/api/improvements/proposals`、`/api/improvements/scan`、`/api/improvements/proposals/{id}/experiment`
- `/api/settings`、`/api/audit`
- `/api/credentials`、`/api/credentials/{provider}`
- `/api/models/test`
- `/api/models/roles`、`/api/models/roles/{role}`、`/api/models/generate`
- `/api/routing/rules`、`/api/routing/rules/{task}`
- `/api/coach/report`、`/api/coach/plan`、`/api/coach/context`
- `/api/zotero/status`、`/api/zotero/sync`、`/api/zotero/import-attachments`
- `/api/ops/status`、`/api/ops/backup`
- `/api/ops/backup/settings`（`GET` / `PUT`）
- `/api/browser/status`、`/api/browser/allowlist`、`/api/browser/actions`
- `/api/browser/actions/{id}/approve`、`/api/browser/actions/{id}/reject`
- `/api/browser/stop`、`/api/browser/resume`

## 13. Codex、CLI 与版本化任务桥梁

`backend.cli` 通过本机 API 读取资料和任务，不继承 Codex 登录态。任务信封使用 `nexus.task-envelope` v1，并用 SHA-256 覆盖任务修订、约束、上下文描述和既有结果；过期结果回写返回 409。

```powershell
uv run python -m backend.cli health
uv run python -m backend.cli search '检索词' --limit 10
uv run python -m backend.cli task-envelope 12
uv run python -m backend.cli task-report 12 --input 'C:\absolute\result.json'
uv run python -m backend.cli collaborate --input 'C:\absolute\collaboration.json'
uv run python -m backend.cli improvements
.\install-codex-skill.ps1
```

多模型协作固定分为 fast 整理和 reasoning 独立审阅，两阶段分别记账并共享运行 ID。改进扫描只从近 30 天重复失败中生成去重提案；只有显式批准后才创建隔离 Agent 任务，不自动部署。

## 14. MCP 只读工具服务

`backend/mcp_server.py` 提供资料检索、学习、教练、科研、Agent 任务与信封、改进提案、Zotero、运维和审计等只读工具。工具直接调用运行中的 Dashboard API；不执行写入、不读取密钥、不做副作用。

先启动 Dashboard，再启动 MCP 服务：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
& '.\.venv\Scripts\python.exe' -m backend.mcp_server
```

在 Cline / VS Code 的 MCP 配置中注册：

```json
{
  "mcpServers": {
    "nexus-ai-pc": {
      "command": "C:\\AI-PC\\app\\dashboard\\.venv\\Scripts\\python.exe",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "C:\\AI-PC\\app\\dashboard"
    }
  }
}
```

## 15. 受控浏览器自动化

浏览器动作走“域名白名单 → 风险分级 → 逐步审批 → 审计 → 紧急停止”：

- `PUT /api/browser/allowlist`：设置允许访问的域名；默认空列表表示全部拒绝。
- `POST /api/browser/actions`：提交 `open` / `click` / `type` / `snapshot` / `close`；`open` 必须命中白名单；`snapshot` 为低风险自动执行，其余进入待审批。
- `POST /api/browser/actions/{id}/approve` / `reject`：人工审批。
- `POST /api/browser/stop` / `resume`：紧急停止与恢复；停止后不接受新动作。
- 每次提交、审批、执行、停止都会写入 `audit_events`；Playwright 未安装时审批返回 503，动作不会执行。

依赖安装（本机已完成，换机器时需要重做）：

```powershell
uv sync --dev
& '.\.venv\Scripts\python.exe' -m playwright install chromium
```

设置接口有意拒绝 `api_key` 等额外字段。密钥只通过凭据接口写入 Windows Credential Manager，不能写入源码、Markdown、日志或 SQLite 设置表。

</details>
