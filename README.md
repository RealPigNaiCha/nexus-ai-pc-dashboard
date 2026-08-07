# Nexus AI-PC Dashboard 部署与运维手册

Nexus AI-PC Dashboard 是只监听本机回环地址的 FastAPI + SQLite 应用。当前可用的真实功能包括：本地 Dashboard、PDF/Markdown/TXT 导入、SQLite 词法检索、本地 BGE + Qdrant 语义/混合检索、FSRS 学习进度、可解释学习教练报告、Crossref/OpenAlex 科研检索与筛选、科研笔记、PaperQA2 论文问答（本地索引 + 带引用回答）、DeepTutor 教学与研究问答、统一 AI 对话（先检索本地资料与学习进度，再生成带引用回答）、Zotero 只读同步、VS Code + Cline 显式 Agent 交接、非敏感设置、Windows 凭据库中的 API 密钥管理、安全模型连通性测试、模型角色路由与最小生成调用、在线备份与磁盘告警、定时自动备份（可配置间隔与保留份数）和审计记录。定时资料监听、自动复习调度和电脑控制尚未接入执行器。新建数据库保持为空，不会自动生成虚构的学习、科研或 Agent 活动。

项目当前状态、安全边界和后续优先级见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。下次继续开发时应先阅读该文件，复用现有数据底座。

模块边界、数据流、API 约定和接手流程见 [DESIGN.md](DESIGN.md)。涉及结构迁移、模型调用或电脑自动化前，应先阅读该设计说明。

产品方向是“图书馆 + 调度中心”：资料、实验和学习证据长期沉淀在本地，Dashboard 连接 Codex、CLI、skills、MCP 和多种模型，但不要求用户放弃更成熟的执行器，也不把长期知识绑定到单一聊天窗口。

普通用户的日常使用说明见 [AI-PC 使用说明](../../docs/AI-PC-使用说明.md)：包含页面导览、首次配置模型、资料导入、学习流程、Zotero 同步、备份和常见问题。

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

`uv` 已安装在 `%USERPROFILE%\.local\bin`，该目录也已写入用户 PATH。安装前已经打开的终端可能仍找不到命令，关闭后重新打开 PowerShell 即可。Dashboard 的启动脚本也会自动回退到 `.venv\Scripts\python.exe`；不要手工把包安装到系统 Python。

## 3. 启动、停止与检查

在 PowerShell 中运行：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\start.ps1
```

`start.ps1` 会在后台启动服务、等待健康检查通过，然后打开浏览器。只启动服务、不打开浏览器：

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
| PDF | `.pdf`，使用 PyMuPDF 提取已有文本层并保留页码 |
| Markdown | `.md`、`.markdown` |
| 纯文本 | `.txt`，支持 UTF-8、UTF-8 BOM 和 GB18030 |
| 单文件大小 | 最大 512 MiB；超过即拒绝 |
| 目录导入 | 递归扫描，单次最多 500 个受支持文件 |
| 暂不支持 | DOCX、EPUB、图片、音视频及其他扩展名 |

扫描版 PDF 目前没有 OCR。此类文件即使能打开，也可能没有可搜索文本；先用人工抽查确认文本层，后续再接 OCRmyPDF/Tesseract 或 Docling。导入不会修改原文件。

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
- 文本按段落切分，超长内容继续拆到最多约 1800 字符的片段；PDF 同时保存页码和页内段落号。

## 5. 词法、语义与混合检索

资料内容保存在 SQLite，全文索引使用 FTS5 的 `unicode61` tokenizer：

- 英文等适合分词、长度至少 3 的查询使用 FTS5，并按 BM25 排序。
- 中文词组和少于 3 个字符的短词自动使用 `LIKE` 子串检索，因此“极限”“连续”可直接搜索。
- 多个查询词使用 AND 语义，即同一片段必须同时包含全部词。
- 网页每次显示最多 20 条；API 的 `limit` 可设为 1 至 100，查询最长 500 字符。
- 返回结果包含标题、来源路径、类型、页码、段落号、片段序号和高亮摘要，可作为引用定位依据。

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

正式索引当前应返回 17 篇文档、251 个向量点。重建会清理旧点后从 SQLite 片段重新生成；失败时不影响 SQLite 关键词检索。

### 5.1 学习进度

- 课程包含目标和可选目标日期。
- 知识点可记录描述和同课程前置关系。
- 每次答题可保存题目、答案、反馈、得分、信心、用时和提示次数。
- FSRS 根据证据生成 Again/Hard/Good/Easy 评级和下一次到期时间。
- 掌握度采用有界证据更新，低分会降低掌握度，提示次数会降低本次证据权重。

### 5.2 科研检索

- 每个科研项目保存研究问题、类型、检索运行、候选论文、筛选决定和研究日志。
- 检索同时请求 Crossref 与 OpenAlex，使用明确超时和 `Nexus-AI-PC/0.1` User-Agent。
- DOI 会规范化并跨来源去重；来源元数据、作者、摘要、引用数和 URL 会合并。
- 只有两个来源都成功后才在单个 SQLite 事务中保存，网络或上游错误不会留下半份检索记录。
- 公共元数据接口不需要用户 API 密钥；论文全文和 Zotero 自动导入尚未接入。

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

- `POST /api/chat/ask`：请求体为 `{question, role, scope, course_id?}`；`role` 只允许 `reasoning` / `fast`，`scope` 为 `all`（资料 + 学习，默认）、`library`（仅资料库）或 `learning`（仅学习进度）。
- 检索结果与学习状态只在调用瞬间拼入提示词；回答返回 `answer`、`evidence`、`learning_state`、`semantic_degraded`、模型信息与 token 统计。
- 自然语言长句在词法检索无结果时，会按中文关键词自动回退检索；语义索引不可用时与现有检索一致地降级到 SQLite。
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

日常配置直接使用 Dashboard 的“设置”页：选择服务商，粘贴密钥并点击“安全保存密钥”。成功后输入框会立即清空，刷新页面也只能读取配置状态。下列 PowerShell 接口主要用于验收和删除凭据。

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

## 8. 登录自启动与日志

注册当前 Windows 用户登录后的计划任务：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
.\install-startup.ps1
Get-ScheduledTask -TaskName 'AI-PC Dashboard'
```

该任务以当前用户身份运行 `start.ps1 -NoBrowser`，并忽略重复实例。当前机器已经注册名为 `AI-PC Dashboard` 的登录任务；重复执行安装脚本会更新现有任务。

移除自启动不会删除应用或数据：

```powershell
Unregister-ScheduledTask -TaskName 'AI-PC Dashboard' -Confirm:$false
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

完整测试：

```powershell
Set-Location 'C:\AI-PC\app\dashboard'
uv run pytest
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

2026-08-07 工作区完整测试为 `135 passed`（含统一 AI 对话测试）；另有一条来自 FastAPI TestClient 依赖的 Starlette/httpx 弃用警告，不影响现有测试通过。

## 11. 常见问题

| 现象 | 处理 |
|---|---|
| 页面显示“演示模式” | 不要直接打开 HTML；运行 `start.ps1` 后访问 `http://127.0.0.1:8765` |
| 启动失败 | 查看 `C:\AI-PC\logs\dashboard.stderr.log`；确认 8765 端口未被其他程序占用 |
| 导入返回 403 | 路径不在两个允许根目录中，先移动资料 |
| 导入返回 400 | 文件类型不支持、路径不是文件/目录，或目录没有支持的文件 |
| 导入返回 422 | 所有候选文件均解析失败；通过 API 文档查看错误详情 |
| 扫描 PDF 搜不到 | 当前没有 OCR；先换文本型 PDF 或后续安装 OCR 工具 |
| 中文结果太多 | 使用更长词组或增加第二个限定词 |
| `uv` 命令不存在 | 关闭后重开 PowerShell；仍不可用时检查用户 PATH 是否包含 `%USERPROFILE%\.local\bin`，已部署环境也可直接用 `.venv\Scripts\python.exe` |

## 12. 当前 API

- `/api/health`、`/api/overview`
- `/api/library/documents`、`/api/library/import`、`/api/library/search`
- `/api/library/semantic/status`、`/api/library/semantic/rebuild`
- `/api/learning/courses`、`/api/learning/concepts`、`/api/learning/dashboard`
- `/api/learning/progress`、`/api/learning/attempts`
- `/api/research/projects`、`/api/research/projects/{id}/notes`
- `/api/research/projects/{id}/searches`、`/api/research/searches/{id}`
- `/api/research/projects/{id}/screening`、`/api/research/projects/{id}/papers/{paper_id}/screening`
- `/api/paperqa/status`、`/api/paperqa/index`、`/api/paperqa/ask`
- `/api/deeptutor/status`、`/api/deeptutor/run`
- `/api/chat/ask`
- `/api/tools`、`/api/agent/status`
- `/api/agent/tasks`、`/api/agent/tasks/{id}/handoff`
- `/api/settings`、`/api/audit`
- `/api/credentials`、`/api/credentials/{provider}`
- `/api/models/test`
- `/api/models/roles`、`/api/models/roles/{role}`、`/api/models/generate`
- `/api/coach/report`、`/api/coach/plan`、`/api/coach/context`
- `/api/zotero/status`、`/api/zotero/sync`
- `/api/ops/status`、`/api/ops/backup`
- `/api/ops/backup/settings`（`GET` / `PUT`）
- `/api/browser/status`、`/api/browser/allowlist`、`/api/browser/actions`
- `/api/browser/actions/{id}/approve`、`/api/browser/actions/{id}/reject`
- `/api/browser/stop`、`/api/browser/resume`

## 13. MCP 只读工具服务

`backend/mcp_server.py` 提供只读 MCP 工具：`search_library`、`learning_progress`、`coach_report`、`coach_plan`、`research_projects`、`zotero_status`、`ops_status`、`audit_log`。工具直接调用运行中的 Dashboard API，共享同一份数据和审计；不执行写入、不读取密钥、不做任何副作用。

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

## 14. 受控浏览器自动化

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
