# Fugu Vibe CLI

[English](README.md) | **中文** | [日本語](README.ja.md)

一个用于从终端使用 Sakana Fugu 风格 API 的 Python CLI。提供交互式提示、可选的编排可视化、项目工作区选择、异步任务提交，以及 Fugu 特有的请求处理。

> 与 Sakana AI 无关联。

## 当前状态

本项目处于早期阶段。稳定路径是正常的文本 `vibe` 会话。

- 文本输入：可用。
- 工作区选择：通过 `-C/--workspace` 可用。
- 编排仪表盘：通过 `--viz` 可选；默认关闭，因为全屏渲染可能干扰终端输入。
- 语音模式：仅为占位。录音器/STT 骨架存在，但按键通话/后台语音交互尚未完全实现。

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
- 使用 `/status` 显示任务状态。
- 使用 `/tasks` 列出活动任务。
- 使用 `/help` 显示会话命令。
- 使用 `/quit`、`/q`、`/exit`、`Ctrl+C` 或 `Ctrl+D` 退出。

常用选项：

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --unlimited
```

仅在需要时启用仪表盘：

```bash
fugu-vibe vibe --viz
```

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
