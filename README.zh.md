# Fugu Vibe CLI

[English](README.md) | **中文** | [日本語](README.ja.md)

一个用于从终端使用 Sakana Fugu 风格 API 的 Python CLI。专为重型开发构建：为 Fugu 提供精确、结构化的工具，完整的会话持久化，以及透明的编排成本监控，同时不干预 Fugu 内部的多 Agent 路由。

> 与 Sakana AI 无关联。

## 当前状态

**Beta 初期。** 五个深化阶段全部实现。CLI 可以承担中型到重型开发任务（5–15 个文件、10 轮工具调用、自动测试闭环），已可投入日常使用。

- 文本输入：**生产就绪**。
- PDF/图片/文件附件：在 `vibe` 中通过 `--file` 或 `/attach` 可用。
- 工作区选择：通过 `-C/--workspace` 可用。
- 会话输出：保存至所选工作区的 `.fugu-vibe/sessions/` 下。
- 异步任务状态/输出：保存至所选工作区的 `.fugu-vibe/tasks/` 下。
- 运行时工作区产物（`.fugu-vibe/` 和 `.fugu-worktrees/`）被 git 忽略。
- **编排仪表盘**：通过 `--viz` 或 `fugu-vibe dashboard` 可选开启；实时展示 token 用量、编排比例和预算告警。
- **Headless 模式**：通过 `fugu-vibe run` 支持 CI/SDK 风格的一次性执行。
- **MCP 集成**：stdio MCP 服务器可通过 `mcp_list_tools` / `mcp_call` 注册和暴露。
- **语音模式**：完整管道（VAD + Faster-Whisper STT + 命令解析）已实现。按键通话和后台语音交互需要手动触发（`record_and_submit()`）；连续自动监听尚未实现。

### Fugu Vibe CLI 的差异化设计

与通用 Agent CLI（Claude Code、OpenHands、Cline）不同，本 CLI **不是外层编排器**。它不计划、分解或验证任务——那是 Fugu 内部 Conductor + TRINITY + Verifier 的工作。相反，它提供**精细、结构化的工具**让 Fugu 精确执行，以及**状态持久化**让长会话在断线后存活。

- **15+ 结构化工具**：`file_edit`（old_string 替换）、`file_write`、`file_read`（支持行号范围）、`file_search`（正则）、`file_glob`、`file_delete`、`bash`（安全分类）、`git_status`、`git_diff`、`git_log`、`run_test`、`run_lint`、`mcp_list_tools`、`mcp_call` 等。
- **所有工具返回结构化 JSON**（exit_code、summary、failures、duration），让 Fugu 的 Verifier 可以瞬间判断结果。
- **自动测试闭环**：`file_edit` 或 `file_write` 后，CLI 自动运行 `run_test` 并将结构化结果注入对话。如果测试失败，Fugu 看到失败 JSON 并在下一轮修复。
- **写入前 diff 预览**：在 `ask` 模式下，每次文件编辑或写入前展示 `git diff` 风格预览（`---` / `+++` / `+` / `-`），用户确认后才执行。
- **安全治理**：四级权限模式（`ask`、`auto-safe`、`auto-edit`、`auto`），命令风险分类，敏感路径拦截，基于 git 的 checkpoint 与 `/undo` 回滚。
- **上下文组装**：`CodebaseIndex` 构建轻量级文件树 + 符号摘要，帮助 Fugu 的 Conductor 选择读取哪些文件。
- **会话持久化**：每轮对话后完整历史保存为 JSONL；断线检测 + 指数退避重连。
- **编排成本监控**：实时 token 预算追踪、编排比例告警、成本估算。
- **Fugu 原生优化**：自适应 `effort` 选择（high/xhigh/max）、`instructions` 模板系统（`.fugu/instructions.md`）、`unlimited_mode` 安全强制执行。

## 安装

需要 Python 3.12+（使用 `from __future__ import annotations` 和 `|` 联合类型）。

```bash
git clone https://github.com/fugu-vibe/fugu-vibe-cli.git
cd fugu-vibe-cli

# 推荐
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .

# 或在你自己的虚拟环境中使用 pip
pip install -e .
```

可选语音依赖：

```bash
uv pip install -e ".[voice]"
# 或：pip install pyaudio webrtcvad faster-whisper
```

## 认证

```bash
export SAKANA_API_KEY="your-key"
```

或通过 CLI 保存：

```bash
fugu-vibe auth login
fugu-vibe auth status
```

如果你使用代理或非官方兼容端点：

```bash
export FUGU_VIBE_API_BASE_URL="https://your-proxy.example/v1"
```

或按命令传入：

```bash
fugu-vibe --base-url https://your-proxy.example/v1 vibe
```

## 交互式使用

启动稳定的文本会话：

```bash
fugu-vibe vibe
```

会话内操作：

- 输入提示词并按回车。
- 使用 `/context` 查看当前提示词上下文。
- 使用 `/compact` 将较早的对话轮次压缩为本地摘要。
- 使用 `/ls [glob]`、`/read <path>` 和 `/search <query> [glob]` 安全地检查工作区文件。
- 使用 `/diff` 查看当前 git 差异。
- 使用 `/apply <patch-file>` 在配置的补丁策略下检查并应用统一差异。
- 使用 `/tools` 查看本地工具策略。
- 使用 `/terminal <command>` 仅在终端工具被显式启用时运行工作区终端命令。
- 使用 `/attach <path>` 添加 PDF/图片/文件上下文。
- 使用 `/files` 和 `/clear-files` 查看或清除已附加的文件。
- 使用 `/status` 显示任务状态。
- 使用 `/tasks` 列出活动任务。
- 使用 `/checkpoint` 手动保存基于 git 的 checkpoint。
- 使用 `/undo` 回滚到上一个 checkpoint。
- 使用 `/help` 显示会话命令。
- 使用 `/quit`、`/q`、`/exit`、`Ctrl+C` 或 `Ctrl+D` 退出。

常用选项：

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --file spec.pdf --file screenshot.png
fugu-vibe vibe --unlimited
fugu-vibe vibe --safety ask           # 每次写入/执行前询问
fugu-vibe vibe --safety auto-safe    # 自动执行安全命令，风险命令询问
```

在会话中附加文件：

```text
/attach spec.pdf
/attach screenshot.png notes.txt
/files
/clear-files
```

附件会在每次发送提示词时附带，直到你清除。图片作为图片输入发送；PDF 和其他文件作为文件输入发送。小型文本/代码文件以内联文本上下文形式发送。大于 25 MB 的附件会在发送前被拒绝。

会话记录写入：

```text
.fugu-vibe/sessions/<timestamp>.md
```

当前上下文元数据写入：

```text
.fugu-vibe/context/current.json
```

工作区文件检查命令是只读的，并限制在所选工作区范围内。它们跳过运行时/缓存目录，如 `.git/`、`.fugu-vibe/`、`.venv/` 和 `node_modules/`。

交互式会话可以在策略启用的工具组下执行 Fugu 函数调用，用于工作区文件、终端、git 和 MCP 桥接工具。模型可以根据当前权限模式自动调用 `file_edit`、`file_write`、`bash`、`run_test`、`git_status` 等。

### 终端执行安全

终端执行默认关闭。要在 `vibe` 中启用，请设置：

```toml
[tools]
terminal_enabled = true
terminal_approval = "ask"
```

然后使用：

```text
/tools
/terminal git status
/terminal python -m pytest -q
```

终端工具被限制在工作区内，会阻止常见的破坏性命令模式（`rm -rf`、`sudo`、`curl | sh`），应用超时，截断显示的输出，并将完整日志保存在 `.fugu-vibe/tool-runs/` 下。

当 `[tools] auto_test_after_edit = true` 时，安全的验证命令（如 `run_test`）可以在编辑成功后自动运行。

### 补丁应用策略

补丁应用默认策略为 `ask-apply`。`/apply <patch-file>` 会验证补丁路径，运行 `git apply --check`，显示差异，并在应用前要求输入 `yes`。设置 `[patch] mode = "propose-only"` 以从 CLI 禁用应用补丁。

## Headless 执行、MCP 与 SDK

非交互式执行单个提示词：

```bash
fugu-vibe run "总结这个仓库"
fugu-vibe run --script task.md --json
```

`--json` 返回结构化结果，包含 `ok`、`content`、`tool_calls`、`rounds` 和选中的 `effort`，适用于 CI 或 SDK 风格集成。

按工作区注册 stdio MCP 服务器：

```bash
fugu-vibe mcp add filesystem python path/to/server.py
fugu-vibe mcp list
fugu-vibe mcp tools filesystem
```

MCP 启用后，Fugu 可以通过 `mcp_list_tools` 发现服务器工具，并通过 `mcp_call` 调用。MCP 配置保存在 `.fugu-vibe/mcp.json`，被 git 忽略。

```toml
[mcp]
enabled = true
timeout_seconds = 30
```

Python SDK 入口：

```python
from fugu_vibe.core.headless import run_headless

result = await run_headless(
    prompt="重构 auth.py",
    workspace="/path/to/project",
    model="fugu-ultra",
    effort="xhigh",
    json_output=True,
)
```

## 在特定工作区中工作

在子命令之前使用 `-C/--workspace`：

```bash
fugu-vibe -C /path/to/project vibe
```

这会在加载项目配置和初始化 git/worktree 处理之前更改进程工作目录。它影响 `vibe`、`submit`、`run`、`config` 等命令。

你也可以通过环境变量设置：

```bash
export FUGU_VIBE_WORKSPACE="/path/to/project"
fugu-vibe vibe
```

## 异步任务

提交任务：

```bash
fugu-vibe submit "重构认证" -p "重构认证模块"
```

将文件作为上下文包含：

```bash
fugu-vibe submit "审查规范" -p "总结这份规范" -f spec.pdf --wait
```

等待完成：

```bash
fugu-vibe submit "分析代码" -p "审查代码库" --wait
```

使用依赖：

```bash
fugu-vibe submit "编写测试" -p "添加测试" --depends-on <task-id>
```

检查状态：

```bash
fugu-vibe status
fugu-vibe status <task-id>
fugu-vibe status --watch
```

附加或取消：

```bash
fugu-vibe attach <task-id>
fugu-vibe cancel <task-id>
```

任务记录存储在 `.fugu-vibe/tasks/` 中。任务记录 Fugu 输出和元数据，并在模型在当前安全策略下调用 `file_edit` 或 `file_write` 时自动应用代码变更。

`submit` 目前在排队/运行中的任务执行期间保持提交进程存活。当你想在同一终端打印最终结果时，请使用 `--wait`。

## 配置

配置按以下顺序加载，优先级从高到低：

1. CLI 命令行参数
2. 环境变量
3. 项目配置：`.fugu-vibe.toml`
4. 用户配置：`~/.config/fugu-vibe/config.toml`
5. 默认值

创建或查看配置：

```bash
fugu-vibe config init
fugu-vibe config init --global
fugu-vibe config show
fugu-vibe config path
fugu-vibe config set model.default fugu-ultra
```

`.fugu-vibe.toml` 示例：

```toml
[api]
base_url = "https://api.sakana.ai/v1"
timeout = 7200
stream_idle_timeout_ms = 7200000

[model]
default = "fugu-ultra"
reasoning_effort = "xhigh"
max_output_tokens = 32768

[tasks]
max_parallel = 5
use_git_worktree = true
auto_merge = true

[prompt]
unlimited_mode = false

[tools]
max_tool_rounds = 10
auto_test_after_edit = true
auto_test_command = "python -m pytest -q"
terminal_enabled = true
terminal_approval = "ask"

[safety]
mode = "ask"               # ask | auto-safe | auto-edit | auto
command_timeout_seconds = 30

[patch]
mode = "ask-apply"
```

请勿提交 API 密钥或包含机密的本地配置。

## 项目 Instructions 模板

在项目根目录创建 `.fugu/instructions.md`，为 Fugu 内部的 Conductor 提供项目特定的上下文（架构、约定、测试策略）。这会影响 Fugu 如何在内部 Agent 之间路由任务。

```markdown
---
project_type: python-backend
framework: fastapi
conventions:
  - 所有地方使用类型注解
  - 优先使用 pydantic 模型进行验证
  - 测试放在 tests/ 目录，镜像 src/ 结构
---

# 项目上下文

这是一个使用 FastAPI + SQLAlchemy + Alembic 的 Python 后端 API。

## 架构
- `src/api/` - 路由处理器
- `src/services/` - 业务逻辑
- `src/models/` - Pydantic + SQLAlchemy 模型
- `src/db/` - 数据库层
- `tests/` - Pytest 测试套件
```

## 编排仪表盘

仅在需要时启用仪表盘：

```bash
fugu-vibe vibe --viz
```

你也可以在一个终端保持 `vibe` 运行，同时在另一个终端打开同一工作区的仪表盘：

```bash
# 终端 1：正常工作
fugu-vibe -C /path/to/project vibe

# 终端 2：监视该工作区的仪表盘
fugu-vibe -C /path/to/project dashboard
```

双终端仪表盘读取所选工作区中的 `.fugu-vibe/events.jsonl`。它展示：

- 实时 token 用量（Input / Output / Orchestration）
- 编排比例（颜色编码告警）
- 预算进度条和成本估算
- Fugu 内部阶段推断（routing / worker / verification / synthesis）
- Checkpoint 历史和回滚状态

## 语音模式

语音模式实现为完整管道：**VAD（语音活动检测）→ Faster-Whisper 本地 STT → 自然语言命令解析 → 文本提示词提交**。

手动触发（当前默认）：

```python
from fugu_vibe.voice.pipeline import VoicePipeline
pipeline = VoicePipeline(workspace="/path/to/project")
result = await pipeline.record_and_submit()
```

CLI 命令（实验性）：

```bash
fugu-vibe vibe --voice
fugu-vibe voice --continuous
```

连续后台监听尚未自动化。`voice --continuous` 命令启动管道，但等待手动触发事件。

## 开发

默认 CLI 输出保持安静。使用 `--verbose` 在子命令之前显示调试日志：

```bash
fugu-vibe --verbose vibe
```

运行测试套件：

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

pytest
python -m ruff check .
mypy fugu_vibe/
```

## 许可证

MIT 许可证。
