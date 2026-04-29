# 変更履歴 / CHANGES

> このファイルは `feat/beta` ブランチにおける全変更内容を記録します。

---

## [feat/beta] 2026-04-17

### 🔴 バグ修正 — 4017エラー（入退室ループ）

#### 根本原因
Discord の WebSocket セッションには **voice session_id** が紐付いている。  
Bot を再起動すると WebSocket セッション自体が新しくなるため、  
古い `session_id` は Discord サーバー側で **Unknown Session (4017)** として無効になる。  
この状態で `connect()` を呼ぶと、discord.py 内部の `reconnect=True` が  
**同じ無効な `session_id`** で再接続を無限リトライし続けるため、  
入退室を繰り返すループが発生していた。

#### 修正内容

**`bot.py`**
- クラス名を `MyBot` → `IrohaBot` に統一（型ヒントとの一致）
- `on_ready` における起動時ボイスセッションクリア処理を強化
  - `voice_state(guild_id, None)` 送信後、`guild.me.voice is None` になるまで最大3秒待機
  - 全ギルドのセッションクリア後にさらに1.5秒待機（Discord 側反映時間を確保）
- `close()` をオーバーライドして Bot 終了時に DB を確実にクローズ
- `.env` の読み込みを `load_dotenv()` + `load_dotenv(dotenv_path="ci/.env")` の二段構えに変更

**`cogs/music.py`**
- `_reset_voice_session()` を刷新
  - Step 1: `VoiceClient.disconnect(force=True)` で内部オブジェクトを破棄
  - Step 2: `ws.voice_state(guild_id, None)` で Discord 側のセッション記録を消去
  - Step 3: `VOICE_STATE_UPDATE` イベントが届き `guild.me.voice is None` になるまで最大5秒待機
- `_ensure_voice()` を刷新
  - `reconnect=False` を指定して discord.py 内部の無限リトライを停止
  - アプリ側で **セッションリセット → 再接続** を最大3回リトライ
  - バックオフ: 2秒 / 4秒 / 6秒（指数バックオフ）
  - `4017` (Unknown Session) と `4006` (Session No Longer Valid) の両方に対応
  - `asyncio.TimeoutError` も捕捉して再試行
  - リセット後に0.5秒待機して Discord 側の反映を確実にする

---

### 🔴 バグ修正 — `data/models.py` が存在しない（Bot 起動不可）

#### 問題
`bot.py` が `from data.models import Database` をインポートしていたが、  
`data/models.py` ファイルが存在しなかったため Bot が起動すらできない状態だった。

#### 修正内容

**新規作成: `data/__init__.py`**  
- `data` パッケージとして認識させるための空ファイル

**新規作成: `data/models.py`**  
- `aiosqlite` ラッパー `Database` クラスを実装
- 以下のテーブルを初期化:
  - `guild_settings` — Guild ごとの設定（prefix, music_channel_id, max_queue 等）
  - `audio_settings` — Guild ごとのオーディオ設定（preset, bass_boost, surround 等）
  - `music_stats` — 音楽再生統計（title, url, duration, played_at）
  - `ai_profiles` — AI 診断プロファイル（music_type, energy_score, genre_scores）
  - `sensitive_cache` — センシティブチェックキャッシュ
- `fetchone` / `fetchall` / `execute` / `executemany` / `commit` / `close` を実装
- WAL モード・外部キー有効化で安全な並行アクセスを保証

---

### 🔴 バグ修正 — `@commands.Cog.listener()` を `discord.ui.View` 内に定義（サイレント失敗）

#### 問題
`discord.ui.View` は `commands.Cog` を継承しておらず、  
`@commands.Cog.listener()` デコレータを持つメソッドを View 内に定義しても  
discord.py はそのメソッドをイベントリスナーとして登録しない（**サイレント失敗**）。

これにより以下のインタラクションが一切機能していなかった：
- キューページネーションボタン（`music:queue_page:{n}`）
- パーティーモードボタン（`party:toggle:`, `party:join_dj:`, `party:next_dj:`, `party:hype:`）
- クイズ回答ボタン（`quiz:ans:`）

#### 修正内容

**`cogs/music.py`**
- `MusicControlView` 内の `on_interaction` を **`Music` Cog** に移動
- `self._cog.bot` → `self.bot` に修正（Cog 内から直接参照）

**`cogs/party.py`**
- `PartyView` 内の `on_interaction` を **`Party` Cog** に移動
- 各分岐に `try/except ValueError` を追加してクラッシュを防止

---

### 🔴 バグ修正 — `__init__.py` の欠如でモジュールロードに失敗

#### 問題
`cogs/`, `cogs/commands/`, `cogs/admin/` に `__init__.py` が存在しなかったため、  
環境によっては Python パッケージとして認識されず Cog のロードに失敗することがあった。

#### 修正内容
- `cogs/__init__.py` を新規作成
- `cogs/commands/__init__.py` を新規作成
- `cogs/admin/__init__.py` を新規作成

---

### 🟡 機能改善 — `ping` コマンドをスラッシュコマンド対応に変更

#### 問題
`cogs/commands/ping.py` の `ping` コマンドが `@commands.command()` のみで定義されており、  
スラッシュコマンド (`/ping`) として使用できなかった。  
また Cog 内に不要な `intents` 定義が含まれていた。

#### 修正内容
- `@commands.command()` → `@commands.hybrid_command()` に変更
- 不要な `intents = discord.Intents.default()` 定義を削除
- スラッシュ / プレフィックス両対応のレスポンス処理を整理

---

### 🟡 機能改善 — `nowplaying` コマンドにエイリアス `now` を追加

- `README.md` に記載されている `IM!now` コマンドに対応するため  
  `aliases=["np", "now"]` を追加

---

### 🟡 機能改善 — `playlist` コマンドの `voice_client` 参照を修正

#### 問題
`playlist` コマンド内で `ctx.voice_client` を参照していたが、  
`_ensure_voice()` が新しい `VoiceClient` を返した後に  
古い変数 `vc` を参照していなかった。

#### 修正内容
`vc_now = ctx.voice_client` で最新の状態を取得するように修正。

---

## テスト結果

| テスト項目 | 結果 |
|---|---|
| 全ファイル 構文チェック (18ファイル) | ✅ PASS |
| モジュール インポートテスト (7モジュール) | ✅ PASS |
| Database CRUD テスト | ✅ PASS |
| GuildManager 操作テスト | ✅ PASS |
| YTDLSource 静的メソッドテスト | ✅ PASS |
| FFmpeg フィルターチェーン テスト | ✅ PASS |
| AI診断エンジン テスト | ✅ PASS |
| センシティブフィルター テスト | ✅ PASS |
| ping レイテンシー分類テスト | ✅ PASS |
| queue ページネーション テスト | ✅ PASS |
| loop モード検証テスト | ✅ PASS |

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `bot.py` | 修正 | IrohaBot クラス化・4017 対策強化・DB クローズ処理追加 |
| `cogs/music.py` | 修正 | 4017 対策・on_interaction を Cog に移動・reconnect=False |
| `cogs/party.py` | 修正 | on_interaction を Cog に移動・ValueError ガード追加 |
| `cogs/commands/ping.py` | 修正 | hybrid_command 化・不要 intents 削除 |
| `data/models.py` | 新規 | Database クラス実装（aiosqlite ラッパー） |
| `data/__init__.py` | 新規 | パッケージ定義 |
| `cogs/__init__.py` | 新規 | パッケージ定義 |
| `cogs/commands/__init__.py` | 新規 | パッケージ定義 |
| `cogs/admin/__init__.py` | 新規 | パッケージ定義 |
| `.github/CHANGES.md` | 新規 | 本ドキュメント |
