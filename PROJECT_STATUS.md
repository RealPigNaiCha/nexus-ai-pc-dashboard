# AI-PC 项目状态与续作清单

更新时间：2026-08-07

本文是下一次任务的首要入口。先核对本文中的路径、服务状态和测试结果，再继续开发；不要重新搭建已经存在的数据底座。

模块边界、数据流和扩展方式见 [DESIGN.md](DESIGN.md)；本文件只维护当前状态与优先级。

## 1. 当前架构

旧 Dashboard 继续作为权威数据与权限底座，外部开源项目只作为可替换能力插件：

- SQLite、FTS5、Qdrant：资料、片段、检索和引用定位。
- FSRS：课程、知识点、答题证据、掌握度和复习时间。
- 现有科研模块：研究问题、Crossref/OpenAlex 检索、去重、筛选和笔记。
- PaperQA2：本地论文索引 + LiteLLM 驱动的带引用论文问答。
- Windows Credential Manager：API 密钥；数据库和浏览器不保存密钥。
- Dashboard：统一入口、显式动作确认和审计。
- 产品定位：图书馆式长期知识底座 + AI/CLI/skills/Codex 的本机调度中心，不替代用户已经熟悉的执行器。
- VS Code + Cline：当前编程 Agent 的显式交接执行器。
- DeepTutor、Codex CLI、Obsidian、Zotero：已安装或已纳入系统，但集成程度不同。

正式服务地址：`http://127.0.0.1:8765`

若部署前已经打开过页面并仍看到旧界面，使用一次 `http://127.0.0.1:8765/?v=20260806-model`。当前 HTML、CSS 和 JavaScript 已禁用持久缓存，后续普通刷新会读取新版本。

## 2. 关键目录

```text
C:\AI-PC\app\dashboard                 正式只读部署目标
C:\AI-PC\workspaces\ai-pc-dashboard   Agent 可修改的 Git 工作区
C:\AI-PC\data\database                SQLite 数据库
C:\AI-PC\data\agent\tasks            只读 Agent 任务说明
C:\AI-PC\data\index                   Qdrant 与本地 Embedding 缓存
C:\AI-PC\data\index\paperqa          PaperQA2 论文索引（docs.pkl + manifest.json）
C:\AI-PC\data\library                 本地资料
C:\AI-PC\vault                        Obsidian Vault 与允许导入目录
C:\AI-PC\tools\deeptutor              DeepTutor v1.5.9
C:\AI-PC\tools\codex\codex.exe       Codex CLI 0.146.1
C:\AI-PC\tools\nodejs\node.exe       Node.js 24.19.0 LTS
C:\AI-PC\data\codex                   Codex 独立 CODEX_HOME
```

开发源仓库：`C:\Users\RealPig\Documents\Codex\2026-08-05\ni\outputs\ai-pc-dashboard`

## 3. 已完成并可用

- 本地 Dashboard、健康检查、设置与审计。
- PDF、Markdown、TXT 导入；SQLite 关键词检索；BGE + Qdrant 语义和混合检索。
- FSRS 学习进度、课程与知识点、答题记录和下一次复习时间。
- Crossref/OpenAlex 科研检索、DOI 去重、论文筛选与研究笔记。
- PaperQA2 论文问答：`POST /api/paperqa/index` 对 `data\library` / `vault` 内 PDF/MD/TXT 建立本地向量快照；`POST /api/paperqa/ask` 复用 `reasoning` / `fast` 模型角色，按调用从 Windows Credential Manager 读取密钥并在进程内构造 LiteLLM Router，返回 `answer`、`context`、`references` 和 `sources`；索引文件只存向量与文档元数据，不存密钥。
- API 密钥写入 Windows Credential Manager，只返回配置状态。
- `POST /api/models/test`：按调用读取密钥并执行只读模型连通性测试。
- 模型角色路由：`reasoning` / `fast` / `vision` 的服务商、模型和 API 地址持久化在 SQLite 设置中，用户可查看和修改；`embedding` 固定使用本地 BGE，不接受外部配置。
- `POST /api/models/generate`：受控的最小文本生成调用，只在调用瞬间读取密钥，按角色选择模型；`model_calls` 记录服务商、模型、角色、耗时和 token，不保存提示词正文或密钥。
- 学习教练：`GET /api/coach/report` 生成可解释进度报告（掌握度、答题趋势、薄弱前置依赖、下一步建议）；`GET /api/coach/context` 把用户问题、带引用资料证据和 FSRS 学习状态组装为只读教学上下文。
- 未来 7 天学习计划：`GET /api/coach/plan` 按到期复习、未开始知识点和薄弱前置生成每日安排，并基于答题时长估算总耗时。
- Zotero 只读同步：`POST /api/zotero/sync` 只读扫描 `C:\AI-PC\data\zotero\zotero.sqlite`，持久化条目、集合、作者和附件路径；服务运行期间每 6 小时自动同步一次；不复制文献文件，不读取任何凭据。
- 运维与备份：`GET /api/ops/status` 报告数据库完整性、磁盘剩余和最近备份；`POST /api/ops/backup` 使用 SQLite 在线备份 API 生成一致性备份并校验。
- 定时自动备份：服务运行期间按 `ops.backup.*` 设置自动执行在线一致性备份，可配置启用开关、间隔（1–720 小时）和保留份数（1–365）；`GET/PUT /api/ops/backup/settings` 读写设置，超过保留份数的旧备份会被清理并记录审计。
- MCP 只读工具服务：`backend/mcp_server.py` 暴露检索、学习、教练、科研、Zotero、运维和审计 8 个只读工具，供 Codex、Cline、CLI 等调用；工具只读、不读取密钥。
- 受控浏览器自动化：Playwright（Chromium Headless Shell）已安装；动作走“域名白名单 → 风险分级 → 逐步审批 → 审计 → 紧急停止”，未批准的 `open/click/type/close` 不会执行。
- DeepTutor 安全适配器：`GET /api/deeptutor/status` 检测运行环境与模型角色；`POST /api/deeptutor/run` 支持 `chat` / `deep_solve` / `deep_question` / `deep_research`，复用 `reasoning` / `fast` 角色和 Windows Credential Manager；密钥只在单次 CLI 调用期间写入独立工作区的 `model_catalog.json`，结束后立即还原无密钥基线；调用指标写入 `model_calls`，动作写入审计。
- 统一 AI 对话：`POST /api/chat/ask` 先检索资料库（自然语言长句自动回退中文关键词）并汇总学习进度，再按 `reasoning` / `fast` 角色调用模型生成带 `[n]` 引用的回答；返回 `answer`、`evidence`、`learning_state`、`semantic_degraded` 与 token 统计，调用写入 `model_calls` 和审计，不持久化提示词或密钥。
- 多轮对话前端：NextChat（MIT）运行在 `127.0.0.1:3000`，通过 `POST /v1/chat/completions`（OpenAI 兼容、支持流式）访问同一本地知识底座；`GET /v1/models` 返回可用角色，调用写入 `model_calls`（operation=`openai_compat_chat`）与审计。
- 官方服务商端点固定到官方 HTTPS 域名；兼容服务只允许 HTTPS 或本机回环 HTTP。
- `model_calls` 记录来源、耗时、状态和错误码，不记录密钥、响应正文或模型列表。
- Agent 任务持久化到 SQLite，刷新网页后仍可读取。
- `GET /api/tools`：报告旧底座和外部工具的实际接入状态。
- `GET /api/agent/status`：检测隔离工作区、VS Code 和 Cline。
- `POST /api/agent/tasks/{id}/handoff`：只接受本机同源请求和 `X-AI-PC-Action: agent-handoff`。
- Agent 交接使用数据库 CAS 状态机防止重复点击；成功状态只记为 `handoff_requested`。
- 完整任务写入只读 Markdown，使用原子写入和 SHA-256 完整性校验。
- Cline URI 只携带任务编号和任务文件路径，不携带完整任务正文或密钥。
- Cline 只能打开 `C:\AI-PC\workspaces` 下批准的工作区，不能修改正式部署目录。

正式数据库在本次开发前的基线为 17 篇文档、251 个向量片段；2026-08-06 部署后已通过 API 复核仍为 17 篇文档、251 个向量点。不要在文档中虚构新的计数。

2026-08-06 晚部署 PaperQA2 后：工作区与正式目录测试均为 114 passed；正式环境已用 `C:\AI-PC\data\library\paperqa-demo`（2 篇 Markdown 示例）建立论文索引（约 77 秒，含首次模型加载），`/api/paperqa/status` 返回 `index.built=true`、`document_count=2`；在未配置模型角色时提问返回 409，`model_calls` 记录 `paperqa_ask/error/role_not_configured`，审计事件正常。示例文件可在“资料库”中删除，不影响代码。

2026-08-08 已接入 NextChat 多轮对话前端与 OpenAI 兼容流式端点；工作区完整测试为 `140 passed`（含统一 AI 对话与兼容端点测试）。

## 4. 已安装但尚未完全接入

- Codex CLI `0.146.1`：已放在固定绝对路径；Dashboard 不继承个人 Codex 登录态，暂不作为网页自动执行器。
- Zotero `9.0.6`：已安装，Dashboard 已接入只读同步（条目、集合、作者、附件路径）；自动同步尚未接入。
- Obsidian `1.13.4`：Vault 已作为 Markdown 资料与笔记目录使用，但没有双向结构化同步。
- Node.js `24.19.0` LTS：安装在项目工具目录，用于前端语法检查和后续工具链。
- OpenAdapt：已完成项目核验，尚未安装和接入。

安装过程的以下无用残留已移到回收区 `C:\AI-PC\backups\trash\2026-08-07-install-residuals`（合计约 420 MiB，可恢复；确认不需要后可直接删除）：

```text
C:\AI-PC\tools\downloads\deeptutor-v1.5.9-37c3db6.incomplete-20260806-1039.zip
C:\AI-PC\tools\downloads\deeptutor-duplicate-venv-incomplete-20260806
C:\AI-PC\tools\deeptutor\.verify-home
C:\AI-PC\tools\deeptutor-git-metadata-37c3db6
C:\AI-PC\tools\deeptutor\DeepTutor-37c3db6df7e886aee4f61c97ec5e618b8ab379e8
```

## 5. 必须保留的安全边界

- 不运行 `deeptutor init`。它会把模型密钥写入 `model_catalog.json`；适配器改为“调用前写入带密钥的临时 catalog、结束后还原无密钥基线”，密钥从不进入参数、日志、SQLite 或审计。
- 不读取、显示或复制 Windows Credential Manager 中的密钥。
- 不把密钥写入源码、SQLite、Markdown、日志、浏览器存储或命令参数。
- Codex 必须使用绝对路径和 `CODEX_HOME=C:\AI-PC\data\codex`。
- Dashboard 不得静默继承个人 Codex 登录状态。
- 正式目录 `C:\AI-PC\app\dashboard` 只用于部署；编程 Agent 只修改隔离 Git 工作区。
- 电脑自动化必须有动作白名单、逐步确认、审计和紧急停止，不能直接给予全局无人值守权限。
- 调度桥梁不能静默继承 Codex 登录态；跨工具同步只传递版本化任务、精简上下文、引用和结果状态。
- 多模型路由必须保留用户选择权，并按成本、质量、隐私、延迟和任务角色记录决策。
- 系统可以提出自我改进，但正式更新必须经过隔离、测试、人工批准、备份和可回滚部署。

## 6. 下一步工作，按优先级

### P0：模型与 DeepTutor 安全适配器

已完成安全模型探针：Credential Manager 按调用读取、端点约束、无密钥调用审计，以及超时、额度不足、上游错误和中途取消测试。下一步：

1. [x] 模型角色配置（`reasoning` / `fast` / `vision`）与最小只读生成调用已接入并部署到正式目录。
2. [x] DeepTutor model catalog 已按“调用前写入、结束后还原”的方式接入，不写入长期配置文件。
3. [x] 接入教学问答、出题和深度研究任务（`/api/deeptutor/run`）；真实生成调用写入同一审计表。

### P1：学习教练闭环

1. [x] 复用现有资料检索和 FSRS，而不是另建学习数据库。
2. [x] 把用户问题、检索证据、答题结果和当前课程目标组成只读教学上下文（`/api/coach/context`）。
3. AI 建议只能更新“建议”字段；掌握度仍由真实答题证据更新。
4. [x] 薄弱前置依赖、可解释进度报告（`/api/coach/report`）和未来 7 天计划（`/api/coach/plan`）已接入。

### P1：统一 AI 对话

1. [x] “AI 对话”页已接入：先检索资料库与学习进度，再按角色生成带引用回答；语义不可用时自动回退中文关键词检索。
2. [x] 回答附带可展开的“来源”（路径、页码/段落、片段）和“学习进度”核对区；模型角色未配置时返回 409 并写入审计。

### P1：多轮对话前端（NextChat）

1. [x] 选用 MIT 开源的 NextChat 作为多轮对话 UI，聊天记录保存在浏览器本地，不新增数据库或用户体系。
2. [x] 后端新增 OpenAI 兼容端点 `POST /v1/chat/completions` 与 `GET /v1/models`：支持多轮 `messages[]`、流式 SSE、角色映射（`reasoning` / `fast`）、本地资料检索与引用；密钥仍只在调用瞬间从 Windows Credential Manager 读取。
3. [x] 每次兼容调用写入 `model_calls`（operation=`openai_compat_chat`、source=`nextchat`）与审计（`chat/openai_completions`），不持久化提示词、回答或密钥。
4. [x] 提供 `start-nextchat.ps1` / `stop-nextchat.ps1`，也可用 `start.ps1 -WithChat` 一次启动 Dashboard 与 NextChat。

### P1：跨工具调度与模型路由

1. 设计版本化任务信封和上下文包，让 Codex CLI、skills、MCP 与网页共享同一资料/任务/结果 ID。
2. 设计按角色、预算、隐私和质量选择模型的路由表；低成本模型优先处理整理、分类和草稿，强模型处理综合与冲突分析。
3. 为每次生成调用记录 provider、model、角色、来源、耗时、成本估算和错误码，支持用户覆盖和人工复核。
4. 保持对话执行器可替换，避免把长期知识绑定到某个聊天窗口或供应商。

### P1：科学学习与反讨好工作流

1. 把网络检索、本地资料、证据分级、反例和不确定性纳入教学与科研提示词模板。
2. 将用户判断标记为假设或决定，要求模型区分来源事实、推断、建议和待验证事项。
3. 对高影响结论增加第二来源、第二模型或人工复核，并保存可复现的检索式和引用。

### P1：科研增强

1. [x] Zotero 只读同步已接入（手动 + 服务运行期间每 6 小时自动），保留条目 ID、集合、作者和附件路径信息。
2. [x] PaperQA2 已接入：本地索引 + 带引用论文问答（`/api/paperqa/index`、`/api/paperqa/ask`），复用模型角色与凭据存储。
3. 增加 PDF 全文解析、扫描件 OCR、研究证据表和可复现检索式导出。

### P2：受控电脑自动化

1. [x] 受控浏览器自动化已接入（Playwright + 白名单 + 审批 + 审计 + 急停）；Windows UI 自动化仍待评估。
2. OpenAdapt 只作为候选执行层，不作为权限系统。
3. 每个动作先生成计划，按风险分级确认；文件删除、安装、外发和账号操作默认阻止。

### P2：运维与迁移

1. [x] Dashboard 已接入备份状态、最近一次一致性检查和磁盘空间告警（`/api/ops/status`、`/api/ops/backup`）；定时自动备份与保留策略已接入（`/api/ops/backup/settings`）。
2. 512 GB 新系统盘已就位；继续复测数据库、向量点、中文检索、凭据状态和登录自启动。
3. 为版本升级增加数据库备份、迁移检查和回滚说明。

### P2：受控自我改进

1. 从失败率、重复劳动、用户修正和检索质量中发现改进信号。
2. 自动生成改进提案、实验补丁和评估报告，但只写入隔离工作区。
3. 通过人工批准后再备份、部署、观察和回滚，记录变更原因、费用影响和测试证据。

## 7. 下次开始时的检查

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/health'
Invoke-RestMethod 'http://127.0.0.1:8765/api/overview'
Invoke-RestMethod 'http://127.0.0.1:8765/api/tools'
Invoke-RestMethod 'http://127.0.0.1:8765/api/agent/status'

Set-Location 'C:\AI-PC\workspaces\ai-pc-dashboard'
git status --short
& '.\.venv\Scripts\python.exe' -m pytest
```

若隔离工作区没有自己的 `.venv`，先使用正式部署环境中的 Python 运行只读测试，或在工作区执行 `uv sync --dev`；不要把虚拟环境提交到 Git。

## 8. 当前验收标准

- 完整 Python 测试通过。
- `git diff --check` 无错误。
- Dashboard 在桌面和移动宽度下无重叠，浏览器控制台无语法错误。
- `/api/tools` 正确区分“已接入”“已安装”“候选”和“未检测到”。
- `/api/models/test` 不泄露密钥，并正确区分端点错误、鉴权、限流、超时和上游错误。
- 统一 AI 对话未配置角色返回 409 并记录 `model_calls` 与审计；回答携带 `evidence` 和 `learning_state`，密钥不进入数据库。
- OpenAI 兼容端点支持多轮上下文与流式 SSE，未配置角色返回 409；`model_calls` 记录 `openai_compat_chat` / `nextchat`，测试确认密钥不进入响应、SQLite 或审计。
- Agent 重复交接返回 409，跨站或缺动作头返回 403，工具缺失返回 503 且任务保持 `queued`。
- 正式数据库在线一致性备份完成后再同步和重启服务。
