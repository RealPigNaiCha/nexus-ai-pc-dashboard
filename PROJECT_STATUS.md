# AI-PC 项目状态与续作清单

更新时间：2026-08-06

本文是下一次任务的首要入口。先核对本文中的路径、服务状态和测试结果，再继续开发；不要重新搭建已经存在的数据底座。

## 1. 当前架构

旧 Dashboard 继续作为权威数据与权限底座，外部开源项目只作为可替换能力插件：

- SQLite、FTS5、Qdrant：资料、片段、检索和引用定位。
- FSRS：课程、知识点、答题证据、掌握度和复习时间。
- 现有科研模块：研究问题、Crossref/OpenAlex 检索、去重、筛选和笔记。
- Windows Credential Manager：API 密钥；数据库和浏览器不保存密钥。
- Dashboard：统一入口、显式动作确认和审计。
- VS Code + Cline：当前编程 Agent 的显式交接执行器。
- DeepTutor、Codex CLI、Obsidian、Zotero：已安装或已纳入系统，但集成程度不同。

正式服务地址：`http://127.0.0.1:8765`

若部署前已经打开过页面并仍看到旧界面，使用一次 `http://127.0.0.1:8765/?v=20260806-agent`。当前 HTML、CSS 和 JavaScript 已禁用持久缓存，后续普通刷新会读取新版本。

## 2. 关键目录

```text
C:\AI-PC\app\dashboard                 正式只读部署目标
C:\AI-PC\workspaces\ai-pc-dashboard   Agent 可修改的 Git 工作区
C:\AI-PC\data\database                SQLite 数据库
C:\AI-PC\data\agent\tasks            只读 Agent 任务说明
C:\AI-PC\data\index                   Qdrant 与本地 Embedding 缓存
C:\AI-PC\data\library                 本地资料
C:\AI-PC\vault                        Obsidian Vault 与允许导入目录
C:\AI-PC\tools\deeptutor              DeepTutor v1.5.9
C:\AI-PC\tools\codex\codex.exe       Codex CLI 0.146.1
C:\AI-PC\data\codex                   Codex 独立 CODEX_HOME
```

开发源仓库：`C:\Users\RealPig\Documents\Codex\2026-08-05\ni\outputs\ai-pc-dashboard`

## 3. 已完成并可用

- 本地 Dashboard、健康检查、设置与审计。
- PDF、Markdown、TXT 导入；SQLite 关键词检索；BGE + Qdrant 语义和混合检索。
- FSRS 学习进度、课程与知识点、答题记录和下一次复习时间。
- Crossref/OpenAlex 科研检索、DOI 去重、论文筛选与研究笔记。
- API 密钥写入 Windows Credential Manager，只返回配置状态。
- Agent 任务持久化到 SQLite，刷新网页后仍可读取。
- `GET /api/tools`：报告旧底座和外部工具的实际接入状态。
- `GET /api/agent/status`：检测隔离工作区、VS Code 和 Cline。
- `POST /api/agent/tasks/{id}/handoff`：只接受本机同源请求和 `X-AI-PC-Action: agent-handoff`。
- Agent 交接使用数据库 CAS 状态机防止重复点击；成功状态只记为 `handoff_requested`。
- 完整任务写入只读 Markdown，使用原子写入和 SHA-256 完整性校验。
- Cline URI 只携带任务编号和任务文件路径，不携带完整任务正文或密钥。
- Cline 只能打开 `C:\AI-PC\workspaces` 下批准的工作区，不能修改正式部署目录。

正式数据库在本次开发前的基线为 17 篇文档、251 个向量片段。部署后应再次通过 API 核对，不要在文档中虚构新的计数。

## 4. 已安装但尚未完全接入

- DeepTutor `v1.5.9`：官方 Apache-2.0 仓库的干净浅克隆，CLI 环境和依赖已验证。当前只显示“已安装”。
- Codex CLI `0.146.1`：已放在固定绝对路径；Dashboard 不继承个人 Codex 登录态，暂不作为网页自动执行器。
- Zotero `9.0.6`：已安装，Dashboard 尚未自动读取或同步 Zotero 数据库。
- Obsidian `1.13.4`：Vault 已作为 Markdown 资料与笔记目录使用，但没有双向结构化同步。
- PaperQA2、OpenAdapt：已完成项目核验，尚未安装和接入。

安装过程还有以下无用残留，合计约 420 MiB。它们不影响运行；后续可在资源管理器确认路径后删除：

```text
C:\AI-PC\tools\downloads\deeptutor-v1.5.9-37c3db6.incomplete-20260806-1039.zip
C:\AI-PC\tools\downloads\deeptutor-duplicate-venv-incomplete-20260806
C:\AI-PC\tools\deeptutor\.verify-home
C:\AI-PC\tools\deeptutor-git-metadata-37c3db6
C:\AI-PC\tools\deeptutor\DeepTutor-37c3db6df7e886aee4f61c97ec5e618b8ab379e8
```

## 5. 必须保留的安全边界

- 不运行 `deeptutor init`。它会把模型密钥写入 `model_catalog.json`。
- DeepTutor 不能只靠环境变量接收密钥；后续必须实现内存 catalog 或运行后销毁的受控临时配置。
- 不读取、显示或复制 Windows Credential Manager 中的密钥。
- 不把密钥写入源码、SQLite、Markdown、日志、浏览器存储或命令参数。
- Codex 必须使用绝对路径和 `CODEX_HOME=C:\AI-PC\data\codex`。
- Dashboard 不得静默继承个人 Codex 登录状态。
- 正式目录 `C:\AI-PC\app\dashboard` 只用于部署；编程 Agent 只修改隔离 Git 工作区。
- 电脑自动化必须有动作白名单、逐步确认、审计和紧急停止，不能直接给予全局无人值守权限。

## 6. 下一步工作，按优先级

### P0：模型与 DeepTutor 安全适配器

1. 从 Credential Manager 只在调用时读取指定服务商密钥。
2. 在进程内构造 DeepTutor model catalog，不写入长期配置文件。
3. 先接只读教学问答、出题和研究任务；每次调用记录模型、耗时、来源和错误码，但不记录密钥。
4. 为超时、额度不足、上游错误和中途取消增加测试。

### P1：学习教练闭环

1. 复用现有资料检索和 FSRS，而不是另建学习数据库。
2. 把用户问题、检索证据、答题结果和当前课程目标组成一次教学上下文。
3. AI 建议只能更新“建议”字段；掌握度仍由真实答题证据更新。
4. 增加周计划、薄弱知识点、前置依赖缺口和可解释的进度报告。

### P1：科研增强

1. 接入 Zotero 只读同步，保留条目 ID、附件路径和集合信息。
2. 评估 PaperQA2，用于带页码或 DOI 引用的论文问答。
3. 增加 PDF 全文解析、扫描件 OCR、研究证据表和可复现检索式导出。

### P2：受控电脑自动化

1. 优先使用 Windows UI Automation、Playwright 或应用专用 API。
2. OpenAdapt 只作为候选执行层，不作为权限系统。
3. 每个动作先生成计划，按风险分级确认；文件删除、安装、外发和账号操作默认阻止。

### P2：运维与迁移

1. 在 Dashboard 增加备份状态、最近一次一致性检查和磁盘空间告警。
2. 新硬盘克隆后复测数据库、向量点、中文检索、凭据状态和登录自启动。
3. 为版本升级增加数据库备份、迁移检查和回滚说明。

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
- Agent 重复交接返回 409，跨站或缺动作头返回 403，工具缺失返回 503 且任务保持 `queued`。
- 正式数据库在线一致性备份完成后再同步和重启服务。
