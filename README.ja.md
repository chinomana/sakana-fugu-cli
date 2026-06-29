# Fugu Vibe CLI

[English](README.md) | [中文](README.zh.md) | **日本語**

Sakana Fugu スタイルの API をターミナルから使用するための Python CLI。インタラクティブプロンプト、オプションのオーケストレーション可視化、プロジェクトワークスペース選択、非同期タスク送信、Fugu 固有のリクエスト処理を提供します。

> Sakana AI とは無関係。

## 現在の状態

このプロジェクトは初期段階です。安定したパスは通常のテキストベース `vibe` セッションです。

- テキスト入力：使用可能。
- PDF/画像/ファイル添付：`vibe` 内で `--file` または `/attach` を介して使用可能。
- ワークスペース選択：`-C/--workspace` を介して使用可能。
- セッション出力：選択したワークスペースの `.fugu-vibe/sessions/` に保存。
- 非同期タスク状態/出力：選択したワークスペースの `.fugu-vibe/tasks/` に保存。
- 実行時ワークスペース成果物（`.fugu-vibe/` および `.fugu-worktrees/`）は git によって無視される。
- オーケストレーションダッシュボード：`--viz` によるオプション；デフォルトは無効。フルスクリーン描画がターミナル入力を妨げる可能性があるため。
- ボイスモード：現在はプレースホルダーのみ。レコーダー/STT の足場は存在するが、プッシュトゥトーク/バックグラウンドボイスインタラクションはまだ完全には実装されていない。

本 CLI はプロンプトとファイルコンテキストを Fugu に送信し、出力を記録する。現在、モデルが生成したパッチをソースツリーに自動適用することはない。

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
- `/context` で現在のプロンプトコンテキストを確認。
- `/compact` で古い会話のターンをローカル要約に圧縮。
- `/ls [glob]`、`/read <path>`、および `/search <query> [glob]` でワークスペースファイルを安全に確認。
- `/diff` で現在の git 差分を確認。
- `/apply <patch-file>` で設定されたパッチポリシー下で統一差分を検査して適用。
- `/tools` でローカルツールポリシーを確認。
- `/terminal <command>` で、ターミナルツールが明示的に有効な場合のみ、ワークスペースターミナルコマンドを実行。
- `/attach <path>` で PDF/画像/ファイルコンテキストを追加。
- `/files` および `/clear-files` で添付ファイルを確認またはクリア。
- `/status` でタスク状態を表示。
- `/tasks` でアクティブなタスクを一覧表示。
- `/help` でセッションコマンドを表示。
- `/quit`、`/q`、`/exit`、`Ctrl+C`、または `Ctrl+D` で終了。

便利なオプション：

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --file spec.pdf --file screenshot.png
fugu-vibe vibe --unlimited
```

セッション中にファイルを添付：

```text
/attach spec.pdf
/attach screenshot.png notes.txt
/files
/clear-files
```

添付ファイルはクリアされるまで、プロンプト送信時に毎回付随される。画像は画像入力として送信；PDF およびその他のファイルはファイル入力として送信。小さなテキスト/コードファイルはテキストコンテキストとしてインライン化される。25 MB を超える添付ファイルは送信前に拒否される。

セッション記録は以下に書き込まれる：

```text
.fugu-vibe/sessions/<timestamp>.md
```

現在のコンテキストメタデータは以下に書き込まれる：

```text
.fugu-vibe/context/current.json
```

ワークスペースファイル検査コマンドは読み取り専用で、選択したワークスペースに制限される。`.git/`、`.fugu-vibe/`、`.venv/`、および `node_modules/` などの実行時/キャッシュディレクトリをスキップする。

インタラクティブセッションは読み取り専用ファイルツール（`file_list`、`file_read`、`file_search`）用の Fugu 関数呼び出しを実行できる。ターミナル実行は自動モデル呼び出しには公開されない。

ターミナル実行はデフォルトで無効。`vibe` で手動ターミナル実行を有効にするには、以下を設定：

```toml
[tools]
terminal_enabled = true
terminal_approval = "ask"
```

次に使用：

```text
/tools
/terminal git status
```

ターミナルツールはワークスペースに制限され、一般的な破壊的コマンドパターンをブロックし、タイムアウトを適用し、表示された出力を切り捨て、完全なログを `.fugu-vibe/tool-runs/` に保存する。Fugu はまだターミナルツールを自動的に呼び出さない。

パッチ適用のデフォルトポリシーは `ask-apply`。`/apply <patch-file>` はパッチパスを検証し、`git apply --check` を実行し、差分を表示し、適用前に `yes` を求める。`[patch] mode = "propose-only"` を設定して、CLI からパッチ適用を無効にする。

必要な場合のみダッシュボードを有効化：

```bash
fugu-vibe vibe --viz
```

同じワークスペースで、`vibe` を一つのターミナルで実行しながら、別のターミナルでダッシュボードを開くことも可能：

```bash
# ターミナル 1: 通常作業
fugu-vibe -C /path/to/project vibe

# ターミナル 2: そのワークスペースのダッシュボードを監視
fugu-vibe -C /path/to/project dashboard
```

2 ターミナルダッシュボードは、選択したワークスペースの `.fugu-vibe/events.jsonl` を読み込む。`vibe` 起動後に生成されたイベントのみを表示する。

## 特定のワークスペースで作業

サブコマンドの前に `-C/--workspace` を使用：

```bash
fugu-vibe -C /path/to/project vibe
```

これはプロジェクト設定の読み込みと git/worktree 処理の初期化の前に、プロセスの作業ディレクトリを変更する。`vibe`、`submit`、`config` などのコマンドに影響する。

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

ファイルをコンテキストとして含める：

```bash
fugu-vibe submit "仕様をレビュー" -p "この仕様を要約" -f spec.pdf --wait
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

タスク記録は `.fugu-vibe/tasks/` に保存される。タスクは Fugu 出力とメタデータを記録するが、まだコード変更をワークスペースに自動適用しない。

`submit` は現在、キュー/実行中のタスクが実行される間、送信プロセスを生存させ続ける。同じターミナルで最終結果を出力したい場合は `--wait` を使用。

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

デフォルトの CLI 出力は静かに保たれる。デバッグログを表示するには、サブコマンドの前に `--verbose` を使用：

```bash
fugu-vibe --verbose vibe
```

ローカルターミナルツールはデフォルトで無効。パッチ適用ポリシーはデフォルトで `ask-apply`；将来のパッチツールはファイルを変更する前に差分を表示して確認すべき。

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
