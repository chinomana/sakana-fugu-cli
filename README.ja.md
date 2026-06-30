# Fugu Vibe CLI

[English](README.md) | [中文](README.zh.md) | **日本語**

Sakana Fugu スタイルの API をターミナルから使用するための Python CLI。重負荷開発向けに構築されており、Fugu に正確で構造化されたツール、完全なセッション永続化、および透明なオーケストレーションコスト監視を提供しつつ、Fugu の内部マルチエージェントルーティングには干渉しない。

> Sakana AI とは無関係。

## 現在の状態

**Beta 初期段階。** 5 つの深化フェーズがすべて実装済み。CLI は中規模から重負荷の開発タスク（5〜15 ファイル、10 ラウンドのツール呼び出し、自動テストループ）を処理でき、日常利用に ready な状態。

- テキスト入力：**本番対応**。
- PDF/画像/ファイル添付：`vibe` 内で `--file` または `/attach` を介して使用可能。
- ワークスペース選択：`-C/--workspace` を介して使用可能。
- セッション出力：選択したワークスペースの `.fugu-vibe/sessions/` に保存。
- 非同期タスク状態/出力：選択したワークスペースの `.fugu-vibe/tasks/` に保存。
- 実行時ワークスペース成果物（`.fugu-vibe/` および `.fugu-worktrees/`）は git によって無視される。
- **オーケストレーションダッシュボード**：`--viz` または `fugu-vibe dashboard` でオプション开启；トークン使用量、オーケストレーション比率、および予算アラートをリアルタイム表示。
- **Headless モード**：`fugu-vibe run` で CI/SDK スタイルのワンショット実行が可能。
- **MCP 統合**：stdio MCP サーバーは `mcp_list_tools` / `mcp_call` を通じて登録および公開可能。
- **ボイスモード**：フルパイプライン（VAD + Faster-Whisper STT + コマンド解析）が実装済み。プッシュトゥトークとバックグラウンドボイスインタラクションは手動トリガー（`record_and_submit()`）が必要；連続自動リスニングはまだ自動化されていない。

### Fugu Vibe CLI の差別化設計

汎用エージェント CLI（Claude Code、OpenHands、Cline）とは異なり、本 CLI **は外部オーケストレーターではない**。タスクを計画、分解、または検証しない——それは Fugu 内部の Conductor + TRINITY + Verifier の役割。代わりに、**細粒度で構造化されたツール**を提供して Fugu が正確に実行でき、**状態の永続化**により長時間実行セッションが切断後も生存する。

- **15+ 構造化ツール**：`file_edit`（old_string 置換）、`file_write`、`file_read`（行範囲対応）、`file_search`（正規表現）、`file_glob`、`file_delete`、`bash`（安全分類）、`git_status`、`git_diff`、`git_log`、`run_test`、`run_lint`、`mcp_list_tools`、`mcp_call` など。
- **すべてのツール結果は構造化 JSON を返す**（exit_code、summary、failures、duration）——Fugu の Verifier が瞬時に判断できる。
- **自動テストループ**：`file_edit` または `file_write` 後、CLI は自動的に `run_test` を実行し、構造化結果を会話に注入。テストが失敗すると、Fugu は失敗 JSON を見て次のラウンドで修正できる。
- **書き込み前 diff プレビュー**：`ask` モードでは、すべてのファイル編集または書き込み前に `git diff` スタイルのプレビュー（`---` / `+++` / `+` / `-`）を表示し、ユーザー確認後に実行。
- **安全ガバナンス**：4 段階の権限モード（`ask`、`auto-safe`、`auto-edit`、`auto`）、コマンドリスク分類、機密パスブロッキング、git ベースの checkpoint と `/undo` ロールバック。
- **コンテキストアセンブリ**：`CodebaseIndex` は軽量ファイルツリー + シンボル要約を構築し、Fugu の Conductor がどのファイルを読むか選択するのを支援。
- **セッション永続化**：各ラウンド後に完全な会話履歴を JSONL として保存；切断検出 + 指数バックオフ再接続。
- **オーケストレーションコスト監視**：リアルタイムトークン予算追跡、オーケストレーション比率アラート、コスト見積もり。
- **Fugu ネイティブ最適化**：適応的 `effort` 選択（high/xhigh/max）、`instructions` テンプレートシステム（`.fugu/instructions.md`）、`unlimited_mode` 安全強制実行。

## インストール

Python 3.12+ が必要（`from __future__ import annotations` および `|` ユニオン型を使用）。

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

オプションのボイス依存関係：

```bash
uv pip install -e ".[voice]"
# または：pip install pyaudio webrtcvad faster-whisper
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
- `/checkpoint` で手動で git ベースの checkpoint を保存。
- `/undo` で最後の checkpoint にロールバック。
- `/help` でセッションコマンドを表示。
- `/quit`、`/q`、`/exit`、`Ctrl+C`、または `Ctrl+D` で終了。

便利なオプション：

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --file spec.pdf --file screenshot.png
fugu-vibe vibe --unlimited
fugu-vibe vibe --safety ask           # すべての書き込み/実行前に確認
fugu-vibe vibe --safety auto-safe    # 安全なコマンドは自動実行、リスクのあるコマンドは確認
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

インタラクティブセッションは、ポリシーで有効化されたツールグループ下で、ワークスペースファイル、ターミナル、git、および MCP ブリッジツール用の Fugu 関数呼び出しを実行できる。モデルは現在の権限モードに基づいて `file_edit`、`file_write`、`bash`、`run_test`、`git_status` などを自動呼び出しできる。

### ターミナル実行の安全性

ターミナル実行はデフォルトで無効。`vibe` で有効にするには、以下を設定：

```toml
[tools]
terminal_enabled = true
terminal_approval = "ask"
```

次に使用：

```text
/tools
/terminal git status
/terminal python -m pytest -q
```

ターミナルツールはワークスペースに制限され、一般的な破壊的コマンドパターン（`rm -rf`、`sudo`、`curl | sh`）をブロックし、タイムアウトを適用し、表示された出力を切り捨て、完全なログを `.fugu-vibe/tool-runs/` に保存する。

`[tools] auto_test_after_edit = true` の場合、安全な検証コマンド（`run_test` など）は編集成功後に自動実行できる。

### パッチ適用ポリシー

パッチ適用のデフォルトポリシーは `ask-apply`。`/apply <patch-file>` はパッチパスを検証し、`git apply --check` を実行し、差分を表示し、適用前に `yes` を求める。`[patch] mode = "propose-only"` を設定して、CLI からパッチ適用を無効にする。

## Headless 実行、MCP、および SDK

プロンプトを入力せずにワンショット実行：

```bash
fugu-vibe run "このリポジトリを要約する"
fugu-vibe run --script task.md --json
```

`--json` は `ok`、`content`、`tool_calls`、`rounds`、および選択された `effort` を含む構造化結果を返し、CI または SDK スタイルの統合に便利。

ワークスペースごとに stdio MCP サーバーを登録：

```bash
fugu-vibe mcp add filesystem python path/to/server.py
fugu-vibe mcp list
fugu-vibe mcp tools filesystem
```

MCP が有効になると、Fugu は `mcp_list_tools` を通じてサーバーツールを発見し、`mcp_call` を通じて呼び出せる。MCP 設定は `.fugu-vibe/mcp.json` に保存され、git によって無視される。

```toml
[mcp]
enabled = true
timeout_seconds = 30
```

Python SDK エントリポイント：

```python
from fugu_vibe.core.headless import run_headless

result = await run_headless(
    prompt="auth.py をリファクタリングする",
    workspace="/path/to/project",
    model="fugu-ultra",
    effort="xhigh",
    json_output=True,
)
```

## 特定のワークスペースで作業

サブコマンドの前に `-C/--workspace` を使用：

```bash
fugu-vibe -C /path/to/project vibe
```

これはプロジェクト設定の読み込みと git/worktree 処理の初期化の前に、プロセスの作業ディレクトリを変更する。`vibe`、`submit`、`run`、`config` などのコマンドに影響する。

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

タスク記録は `.fugu-vibe/tasks/` に保存される。タスクは Fugu 出力とメタデータを記録し、モデルが現在の安全ポリシー下で `file_edit` または `file_write` を呼び出したときにコード変更を自動適用する。

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

API キーまたは機密を含むローカル設定をコミットしないでください。

## プロジェクト Instructions テンプレート

プロジェクトルートに `.fugu/instructions.md` を作成して、Fugu 内部の Conductor にプロジェクト固有のコンテキスト（アーキテクチャ、規約、テスト戦略）を提供する。これは Fugu が内部エージェント間でタスクをどうルーティングするかに影響する。

```markdown
---
project_type: python-backend
framework: fastapi
conventions:
  - すべての場所で型ヒントを使用
  - 検証には pydantic モデルを優先
  - テストは tests/ ディレクトリに、src/ 構造をミラーする
---

# プロジェクトコンテキスト

FastAPI + SQLAlchemy + Alembic を使用した Python バックエンド API。

## アーキテクチャ
- `src/api/` - ルートハンドラー
- `src/services/` - ビジネスロジック
- `src/models/` - Pydantic + SQLAlchemy モデル
- `src/db/` - データベースレイヤー
- `tests/` - Pytest テストスイート
```

## オーケストレーションダッシュボード

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

2 ターミナルダッシュボードは、選択したワークスペースの `.fugu-vibe/events.jsonl` を読み込む。以下を表示する：

- リアルタイムトークン使用量（Input / Output / Orchestration）
- オーケストレーション比率（カラーアラート）
- 予算進捗バーとコスト見積もり
- Fugu 内部ステージ推論（routing / worker / verification / synthesis）
- Checkpoint 履歴とロールバック状態

## ボイスモード

ボイスモードはフルパイプラインとして実装：**VAD（音声活動検出）→ Faster-Whisper ローカル STT → 自然言語コマンド解析 → テキストプロンプト送信**。

手動トリガー（現在のデフォルト）：

```python
from fugu_vibe.voice.pipeline import VoicePipeline
pipeline = VoicePipeline(workspace="/path/to/project")
result = await pipeline.record_and_submit()
```

CLI コマンド（実験的）：

```bash
fugu-vibe vibe --voice
fugu-vibe voice --continuous
```

連続バックグラウンドリスニングはまだ自動化されていない。`voice --continuous` コマンドはパイプラインを起動するが、手動トリガーイベントを待つ。

## 開発

デフォルトの CLI 出力は静かに保たれる。デバッグログを表示するには、サブコマンドの前に `--verbose` を使用：

```bash
fugu-vibe --verbose vibe
```

テストスイートを実行：

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

pytest
python -m ruff check .
mypy fugu_vibe/
```

## ライセンス

MIT ライセンス。
