# 第三方组件说明

本包附带或会安装以下第三方组件：

- `uv 0.12.1`，Astral Software Inc.，MIT 或 Apache-2.0。本包按 MIT 条款再分发，许可文本见 `licenses/uv-LICENSE-MIT.txt`。
- Dashboard 的 Python 依赖由 `uv.lock` 锁定并在安装时从软件包索引下载，各自许可由对应项目声明。
- 本地向量模型 `BAAI/bge-small-zh-v1.5` 在安装时下载，使用前请核对模型发布页的当前许可与使用限制。
- Playwright Chromium 运行库在安装时下载，遵循 Chromium 和 Playwright 各自许可。
- DeepTutor CLI v1.5.9 在安装时从 [HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor) 的固定提交 `37c3db6df7e886aee4f61c97ec5e618b8ab379e8` 构建并以非 editable 方式安装；临时源码安装后删除。其 CLI 运行依赖固定为 `loguru==0.7.3`、`json-repair==0.63.2` 和 `croniter==6.2.4`。

本包不附带或自动安装 Codex CLI、NextChat、Obsidian、Zotero、Visual Studio Code、Cline、Git for Windows 和 Node.js；这些 App 请从各自官方来源手动安装。相关名称和商标归各自权利人所有。

Nexus AI-PC Dashboard 项目本身采用 MIT License，完整文本随源码根目录的 `LICENSE` 文件发布。
