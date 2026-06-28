# cc-context-usage

[English](README.md) | **日本語**

**Claude（LLM）自身**が、**自分の** context window 使用率を実数で把握するためのツールです。
**Claude Desktop**（Cowork / local agent mode）と **Claude Code CLI** の両方に対応し、
`/context` スラッシュコマンドの副作用を避けつつ値を取得します。

## なぜ必要か

`/context` は「次ターンの推定値」を返し、かつ副作用（askuserquestion の消失等）があります。
本ツールは代わりに、**直前の API request の実投入トークン**
（`input + cache_creation + cache_read`）を読み取ります。これは
[Claude Code statusLine の `used_percentage`](https://code.claude.com/docs/en/statusline)
と同じ input-only 基準です。

この値は **context window 監視** のためのもので、課金やレート制限とは別概念です
（cache read は課金単価が低く、多くのモデルで ITPM レート制限のカウント外）。MCP tool として
Claude 自身が呼び出せるため、セッション分割・引き継ぎ・スコープ縮小を判断する前の
*self-check* に向いています（推測ではなく実数で判断できる）。

## アーキテクチャ

1 つの Python パッケージに、共有 core の上で動く 2 つの薄い MCP サーバー。仕組みは環境ごとに
異なりますが、LLM から見える tool と出力形は同一です。

```
src/cc_context/
  core.py          共有: 正規化 / token limit / contract / rate-limit 整形
  audit_source.py  Desktop アダプタ: session の audit.jsonl を読む
  dump_source.py   CLI アダプタ: statusLine dump を読む（+ fail-loud な schema 検証）
  desktop.py       Claude Desktop 用 MCP サーバー entrypoint（cc-context-desktop）
  cli.py           Claude Code CLI 用 MCP サーバー entrypoint（cc-context-cli）
  limits.json      モデル別 context window limit（パッケージ data、importlib.resources で読込）
scripts/statusline-wrapper.sh   CLI アダプタが読む dump を生成する
```

両サーバーとも MCP サーバー **`cc-context`** として登録され、同じ正規化 JSON を返す
`get_current_context_usage` を公開します。**実行時のルーティングはありません**。
自分の環境に合うアダプタをインストールしてください。

## 必要要件

- **Python 3.10+** — MCP サーバーは Python パッケージです。インストーラは venv を作って
  `pip install` しますが、既存の interpreter を自動検出するだけで **Python 自体は入れません**。
  Windows の PATH 上の `python` は Microsoft Store の *alias stub*（実体なし）のことが多いので、
  本物の Python を [`py` ランチャー / python.org](https://www.python.org/downloads/) か
  `winget install Python.Python.3.12` で導入してください（導入後はインストーラが自動検出します）。
- **Claude Desktop**（Cowork）および/または **Claude Code CLI** — 使う方のアダプタを入れます。
- **git** — この repo を clone するため（clone-and-run-in-place。次節参照）。

## 作業ディレクトリと install 先

**まず恒久的な置き場所を決め、そこに clone してから install してください** — clone 先の
ディレクトリが*そのまま* install 先であり、コピー元として捨てる一時 clone ではありません。
（後で clone を移動した場合は、移動先で `install-cli.sh` を再実行してパスを貼り直してください。）

- **作業ディレクトリ（CWD）は無関係です。** `install-cli.sh` は全てのパスを **script 自身の位置**
  （と `$HOME`）から導出し、CWD は使いません。MCP は **user scope** で登録するため、どのセッション
  からでも（各セッションの `cwd` に関わらず）使えます。`bash /path/to/cc-context-usage/scripts/install-cli.sh`
  でも `cd` してから実行でも結果は同一です。
- **clone はその場に残してください — clone-and-run-in-place 方式です。** install 後も repo は
  runtime で参照されます: `statusLine.command` は **clone 内の** `scripts/statusline-wrapper.sh`
  を指し（毎ターン実行、コピーではない）、venv も既定で **clone 内の** `.venv` に作られます。
  **clone を削除・移動すると statusLine と MCP が壊れます。** Python パッケージ自体は venv に
  コピーされる（通常の非 editable な `pip install`）ため `src/` は runtime で読まれませんが、
  wrapper スクリプトと venv は読まれます。clone を削除可能にしたい場合は、venv を別の場所に作り
  （`install-cli.sh /path/to/venv`）、**かつ** wrapper を安定パスにコピーして `statusLine.command`
  を自分でそこへ向けてください。

## インストール — Claude Desktop (Cowork)

**簡単（Windows）:** `powershell -ExecutionPolicy Bypass -File scripts\install-desktop.ps1`
— venv 作成・パッケージ install・`claude_desktop_config.json` への `cc-context` エントリ
マージ（事前に backup）を行います。その後 Claude Desktop を再起動してください。
（動作する実体を自動検出します — `py` ランチャー→`python`/`python3` の順、Microsoft Store の
alias stub は無視。必要なら `-PythonExe py` で上書き。）手動手順:

```bash
pip install .
```

`claude_desktop_config.json` に登録（`command` = venv の python、args が desktop entrypoint を起動）:

```json
{
  "mcpServers": {
    "cc-context": {
      "command": "/abs/path/to/.venv/bin/python",
      "args": ["-m", "cc_context.desktop"]
    }
  }
}
```

Claude Desktop を再起動し、Claude に `get_current_context_usage` を実行させてください。
（`get_context_history` と `get_session_meta` も利用可。`get_session_meta` は email / cwd /
process 名などの PII を**意図的に返しません**）。

### Desktop の精度（best-effort）

Desktop では MCP サーバーは共有プロセスで、**どの会話から呼ばれたかを受け取れません**。さらに
cowork の audit はターン終了時に flush されます。そのため `session_id` 省略時は **最新 mtime の
audit を自動選択** し、*過去の*セッションを掴む（新しい会話の初回など）/ 1 ターン遅れることが
あります。返り値に `status`（`ok`/`stale`/`unknown`）と `last_event_age_seconds` を付け、鮮度を
判断でき、数値を黙って隠すことはしません。**正確に測るには `session_id` を渡してください** —
cowork では作業ディレクトリ末尾の `local_<uuid>` です。（`CC_CONTEXT_STALE_SECONDS` で stale
しきい値を調整、既定 600）。手動確認だけなら `/context` でも可。**確実なのは CLI アダプタ**
（statusLine が毎ターン現セッションの実数を渡す）。

## インストール — Claude Code CLI

**簡単:** `scripts/install-cli.sh` — venv 作成・パッケージ install・`cc-context` MCP サーバー
登録（`claude mcp add`、user scope）・statusLine を同梱 wrapper に設定（`settings.json` を
backup、既存 statusLine は上書きしない）を行います。`settings.json` が JSON として
parse できない場合、statusLine ステップは graceful に skip されます（MCP サーバー登録は実行）。
自分で statusLine を配線する場合は `CC_INSTALL_SKIP_STATUSLINE=1` を渡してください。
手動手順 — 2 つの部品（wrapper が値を捕捉、MCP サーバーが提供）:

1. **statusLine wrapper**（権威ある値を dump ファイルに捕捉）。`~/.claude/settings.json` に:

   ```jsonc
   "statusLine": {
     "type": "command",
     "command": "/abs/path/to/scripts/statusline-wrapper.sh"
   }
   ```

   権威ある `used_percentage` は statusLine コマンドにしか届かないため、この捕捉ステップは必須です。

2. **MCP サーバー**（dump を読む）。Claude Code の MCP 設定に `cc-context-cli` を登録
   （`python -m cc_context.cli`）。assistant の 1 ターン経過後、`get_current_context_usage`
   が使用量を返します。登録は **user scope**（`claude mcp add --scope user …`）で行ってください。
   既定の `local` scope はコマンドを実行したディレクトリに紐づくため、別ディレクトリのセッションで
   見えなくなります。

## 値の解釈（意見 — 規範ではない）

このツールは事実を返します。ある割合が「あなたにとって何を意味するか」は、モデル・ワークフロー・
許容度によります。個人的な目安（**一例であり処方ではありません**）:
〜30% 余裕 / 60〜80% 要注意 / 80%+ 分割を検討。自分の環境に合わせて調整してください。
ツールは意図的に閾値を埋め込んでいません。

## Python を入れたくない CLI ユーザー向け

Python の MCP サーバーを入れたくない場合、dump ファイルは素の JSON なので直接読めます
（例。維持されるインターフェースではありません）:

```bash
jq '.context_window.used_percentage' "$(ls -t /tmp/cc-context-*.json | head -1)"
```

## statusLine を使っているユーザー向け

wrapper は **ccstatusline** がインストール済みなら表示用に pass-through し、無ければ
dump-only モードに fallback します。つまりサポート対象は **ccstatusline ユーザー** と
**statusLine 未使用ユーザー** の 2 つです。**別の** statusLine コマンドを既に使っている場合は、
`CLAUDE_CONTEXT_WRAPPED_CMD` で wrapper からそこへ渡す（または wrapper を読んで改造する）
— このケースは DIY で、公式サポート対象外です。

## プライバシー / ローカルデータ

statusLine wrapper は Claude Code からの statusLine JSON を**そのまま**
`$CLAUDE_CONTEXT_DUMP_DIR/cc-context-<session_id>.json`（既定 `/tmp`）に書き出します。
この payload には作業ディレクトリやコスト数値などの session metadata が含まれます。
**あなたのマシン内に留まり**、本ツールがどこかへ送信することはありません。ただし共有・
マルチユーザーのホストでは、`CLAUDE_CONTEXT_DUMP_DIR` を専用ディレクトリに向ける、
あるいは定期的に消すことを検討してください。

MCP tool 自体は **basename のみ**（例: `audit.jsonl`）を返し、絶対パスは返しません。
したがってツール出力にユーザー名やマシン構成が露出することはありません。

## アンインストール

- **CLI:** `scripts/uninstall-cli.sh` — `cc-context` MCP サーバー（user scope）の登録解除、
  `statusLine` が本 repo の wrapper を指している場合のみ revert（事前 backup）、venv 削除。
- **Desktop (Windows):** `powershell -ExecutionPolicy Bypass -File scripts\uninstall-desktop.ps1`
  — `claude_desktop_config.json` から `cc-context` エントリを削除（事前 backup、他エントリは
  保持）、venv 削除。完了後に Claude Desktop を再起動してください。

## 検証スタンス

これは maintainer の内部セットアップから派生した公開エディションで、**ここで継続的に
dogfooding はしていません**。正しさは repo 自身のチェックで担保します。CI が pytest スイート
（core + 両アダプタ、synthetic fixture）と wrapper の shellcheck を実行します。メンテナンスは
パートタイムで SLA なし。設計議論は Discussions で歓迎します。

## ライセンス

[Apache-2.0](LICENSE)。[`NOTICE`](NOTICE) と [`SECURITY.md`](SECURITY.md) も参照してください。
