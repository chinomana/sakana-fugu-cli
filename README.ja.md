# Fugu Vibe CLI

[English](README.md) | [中文](README.zh.md) | **日本語**

Sakana Fugu スタイルの API をターミナルから使用するための Python CLI。インタラクティブプロンプト、オプションのオーケストレーション可視化、プロジェクトワークスペース選択、非同期タスク送信、Fugu 固有のリクエスト処理を提供します。

> Sakana AI とは無関係。

## 現在の状態

このプロジェクトは初期段階です。安定したパスは通常のテキストベース `vibe` セッションです。

- テキスト入力：使用可能。
- ワークスペース選択：`-C/--workspace` を介して使用可能。
- オーケストレーションダッシュボード：`--viz` によるオプション；デフォルトは無効。フルスクリーン描画がターミナル入力を妨げる可能性があるため。
- ボイスモード：現在はプレースホルダーのみ。レコーダー/STT の足場は存在するが、プッシュトゥトーク/バックグラウンドボイスインタラクションはまだ完全には実装されていない。

## インストール

Python 3.11–3.13 を使用。Python 3.14 は macOS で依存関係/実行時の問題が発生する可能性がある。

```bash
git clone https://github.com/fugu-vibe/fugu-vibe-cli.git
cd fugu-vibe-cli

# 推奨
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .

# または独自の仮想環境内で pip を使用
pip install -e .
```

## 認証

```bash
export SAKANA_API_KEY="your-key"
```

または CLI を通じて保存：

```bash
fugu-vibe auth login
fugu-vibe auth status
```

プロキシまたは非公式の互換エンドポイントを使用する場合：

```bash
export FUGU_VIBE_API_BASE_URL="https://your-proxy.example/v1"
```

またはコマンドごとに渡す：

```bash
fugu-vibe --base-url https://your-proxy.example/v1 vibe
```

## インタラクティブな使用

安定したテキストセッションを開始：

```bash
fugu-vibe vibe
```

セッション内：

- プロンプトを入力して Enter を押す。
- `/status` でタスク状態を表示。
- `/tasks` でアクティブなタスクを一覧表示。
- `/help` でセッションコマンドを表示。
- `/quit`、`/q`、`/exit`、`Ctrl+C`、または `Ctrl+D` で終了。

便利なオプション：

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --unlimited
```

必要な場合のみダッシュボードを有効化：

```bash
fugu-vibe vibe --viz
```

## 特定のワークスペースで作業

サブコマンドの前に `-C/--workspace` を使用：

```bash
fugu-vibe -C /path/to/project vibe
```

これはプロジェクト設定の読み込みと git/worktree 処理の初期化の前に、プロセスの作業ディレクトリを変更します。`vibe`、`submit`、`config` などのコマンドに影響します。

環境変数で設定することも可能：

```bash
export FUGU_VIBE_WORKSPACE="/path/to/project"
fugu-vibe vibe
```

## 非同期タスク

タスクを送信：

```bash
fugu-vibe submit "認証のリファクタリング" -p "認証モジュールをリファクタリングする"
```

完了を待つ：

```bash
fugu-vibe submit "コードを分析" -p "コードベースをレビュー" --wait
```

依存関係を使用：

```bash
fugu-vibe submit "テストを書く" -p "テストを追加" --depends-on <task-id>
```

状態を確認：

```bash
fugu-vibe status
fugu-vibe status <task-id>
fugu-vibe status --watch
```

アタッチまたはキャンセル：

```bash
fugu-vibe attach <task-id>
fugu-vibe cancel <task-id>
```

## 設定

設定は以下の順序で読み込まれ、優先度が高い順です：

1. CLI コマンドライン引数
2. 環境変数
3. プロジェクト設定：`.fugu-vibe.toml`
4. ユーザー設定：`~/.config/fugu-vibe/config.toml`
5. デフォルト値

設定の作成または確認：

```bash
fugu-vibe config init
fugu-vibe config init --global
fugu-vibe config show
fugu-vibe config path
fugu-vibe config set model.default fugu-ultra
```

`.fugu-vibe.toml` の例：

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

API キーまたは機密を含むローカル設定をコミットしないでください。

## ボイスモード

ボイスモードは現在プレースホルダーです。コードにはレコーダー/STT の足場が含まれているが、プッシュトゥトークと連続ボイスインタラクションはまだプロダクション対応ではない。

以下のコマンドは存在する可能性があるが、安定しているとは扱わない：

```bash
fugu-vibe vibe --voice
fugu-vibe voice --continuous
```

## 開発

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

pytest
ruff check .
mypy fugu_vibe/
```

## ライセンス

MIT ライセンス。
