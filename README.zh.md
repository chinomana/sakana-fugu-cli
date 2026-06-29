# Fugu Vibe CLI

[English](README.md) | **中文** | [日本語](README.ja.md)

一个用于从终端使用 Sakana Fugu 风格 API 的 Python CLI。提供交互式提示、可选的编排可视化、项目工作区选择、异步任务提交，以及 Fugu 特有的请求处理。

> 与 Sakana AI 无关联。

## 当前状态

本项目处于早期阶段。稳定路径是正常的文本 `vibe` 会话。

- 文本输入：可用。
- PDF/图片/文件附件：在 `vibe` 中通过 `--file` 或 `/attach` 可用。
- 工作区选择：通过 `-C/--workspace` 可用。
- 会话输出：保存至所选工作区的 `.fugu-vibe/sessions/` 下。
- 异步任务状态/输出：保存至所选工作区的 `.fugu-vibe/tasks/` 下。
- 运行时工作区产物（`.fugu-vibe/` 和 `.fugu-worktrees/`）被 git 忽略。
- 编排仪表盘：通过 `--viz` 可选；默认关闭，因为全屏渲染可能干扰终端输入。
- 语音模式：仅为占位。录音器/STT 骨架存在，但按键通话/后台语音交互尚未完全实现。

本 CLI 将提示词和文件上下文发送给 Fugu，并记录输出。目前尚未自动将模型生成的补丁应用到源代码树。

## 安装

使用 Python 3.11–3.13。Python 3.14 在 macOS 上可能遇到依赖/运行时问题。

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
- 使用 `/help` 显示会话命令。
- 使用 `/quit`、`/q`、`/exit`、`Ctrl+C` 或 `Ctrl+D` 退出。

常用选项：

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --file spec.pdf --file screenshot.png
fugu-vibe vibe --unlimited
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

交互式会话可以执行 Fugu 函数调用，用于工作区文件工具（`file_list`、`file_read`、`file_search`、`file_mkdir`、`file_write`）。终端执行不会暴露给自动模型调用。

终端执行默认关闭。要在 `vibe` 中启用手动终端运行，请设置：

```toml
[tools]
terminal_enabled = true
terminal_approval = "ask"
```

然后使用：

```text
/tools
/terminal git status
```

终端工具被限制在工作区内，会阻止常见的破坏性命令模式，应用超时，截断显示的输出，并将完整日志保存在 `.fugu-vibe/tool-runs/` 下。Fugu 目前还不会自动调用终端工具。

补丁应用默认策略为 `ask-apply`。`/apply <patch-file>` 会验证补丁路径，运行 `git apply --check`，显示差异，并在应用前要求输入 `yes`。设置 `[patch] mode = "propose-only"` 以从 CLI 禁用应用补丁。

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

双终端仪表盘读取所选工作区中的 `.fugu-vibe/events.jsonl`。它只显示 `vibe` 启动后产生的事件。

## 在特定工作区中工作

在子命令之前使用 `-C/--workspace`：

```bash
fugu-vibe -C /path/to/project vibe
```

这会在加载项目配置和初始化 git/worktree 处理之前更改进程工作目录。它影响 `vibe`、`submit`、`config` 等命令。

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

任务记录存储在 `.fugu-vibe/tasks/` 中。任务记录 Fugu 输出和元数据，但尚未自动将代码更改应用到工作区。

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
```

请勿提交 API 密钥或包含机密的本地配置。

## 语音模式

语音模式当前仅为占位。代码中包含录音器/STT 骨架，但按键通话和连续语音交互尚未达到生产就绪状态。

以下命令可能存在，但不应视为稳定：

```bash
fugu-vibe vibe --voice
fugu-vibe voice --continuous
```

## 开发

默认 CLI 输出保持安静。使用 `--verbose` 在子命令之前显示调试日志：

```bash
fugu-vibe --verbose vibe
```

本地终端工具默认关闭。补丁应用策略默认为 `ask-apply`；未来的补丁工具应在修改文件前显示差异并询问。

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

pytest
ruff check .
mypy fugu_vibe/
```

## 许可证

MIT 许可证。
