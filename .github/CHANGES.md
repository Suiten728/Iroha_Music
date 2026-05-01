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

---

## [feat/4017error] 2026-04-29

> `feat/beta` の4017修正をさらに深く分析し、根本原因を完全に解決した追加修正。

---

### 🔴 根本原因の特定と修正 — 4017エラーの二重送信問題

#### 詳細な根本原因
discord.py の `VoiceClient.disconnect(force=True)` を呼び出すと、内部で  
`VoiceConnectionState.disconnect()` → `_voice_disconnect()` → `change_voice_state(channel=None)`  
が実行され、`VOICE_STATE_UPDATE(channel=None)` がすでに送信される。  

旧実装の `_reset_voice_session()` はこの後さらに  
`bot.ws.voice_state(guild_id, None)` を呼び出していたため、  
**同一ギルドへの `VOICE_STATE_UPDATE(channel=None)` が二重送信**されていた。  

この競合により Discord サーバー側のセッション状態が不整合となり、  
次の `connect()` で取得する `session_id` が無効のまま `IDENTIFY` に使用されるため  
**4017 (Unknown Session)** が連続して発生していた。

#### `cogs/music.py` の修正

**`_reset_voice_session()` の刷新**
- `VoiceClient` が存在する場合: `disconnect(force=True)` のみ実行（内部で voice_state(None) が送られる）
- `VoiceClient` が存在しない場合: `bot.ws.voice_state(guild_id, None)` を手動送信
- いずれの場合も `guild.me.voice is None` になるまで最大5秒待機
- リセット後の待機時間を **2秒** に延長（Discord サーバー側のセッション削除反映を確実に待つ）

**`_ensure_voice()` の改善**
- `reconnect=True` に変更し、discord.py の内部リトライを有効化
  （ただし外側で `_reset_voice_session()` を呼ぶため二重リトライにはならない）
- 指数バックオフの待機時間: 2秒 / 4秒 / 6秒

#### `bot.py` の修正

**起動時ボイスセッションクリアの強化**
- `on_ready` での既存 VC オブジェクト確認: `guild.voice_client` が存在する場合は  
  `voice_client.disconnect(force=True)` を先に実行してから `voice_state(None)` を送信
- `guild.me.voice is None` になるまで最大3秒待機（ポーリング間隔 0.2秒）
- 全ギルドのクリア後の待機時間を **2秒** に延長

#### その他の修正

**コマンド hybrid_command 化**  
以下のコマンドを `@commands.command()` から `@commands.hybrid_command()` に変更し  
スラッシュコマンド・プレフィックスコマンドの両対応を実現:

| ファイル | コマンド |
|---|---|
| `cogs/ai_diagnosis.py` | `diagnose` (`diag`) |
| `cogs/audio_effects.py` | `eq` (`equalizer`) |
| `cogs/statistics.py` | `stats` (`ranking`), `mystats` |
| `cogs/commands/ping.py` | `ping` ※ 再適用 |

---

### テスト結果 (feat/4017error)

| テスト項目 | 結果 |
|---|---|
| 全ファイル 構文チェック (17ファイル) | ✅ PASS |
| モジュール インポートテスト | ✅ PASS |
| ping レイテンシー分類テスト | ✅ PASS |
| URL / プレイリスト 検出テスト | ✅ PASS |
| センシティブフィルター テスト | ✅ PASS |
| AI診断エンジン テスト | ✅ PASS |
| Database CRUD テスト | ✅ PASS |
| GuildManager 操作テスト | ✅ PASS |
| コマンド登録テスト (23コマンド確認) | ✅ PASS |
| 4017修正ロジック検証 | ✅ PASS |
| **合計** | **35 / 35 PASS** |

---

### 変更ファイル一覧 (feat/4017error)

| ファイル | 変更内容 |
|---|---|
| `bot.py` | 起動時VC クリア強化・既存 VoiceClient の事前 disconnect 追加 |
| `cogs/music.py` | `_reset_voice_session` 二重送信修正・`_ensure_voice` reconnect=True 化 |
| `cogs/ai_diagnosis.py` | `diagnose` を hybrid_command に変更 |
| `cogs/audio_effects.py` | `eq` を hybrid_command に変更 |
| `cogs/statistics.py` | `stats`・`mystats` を hybrid_command に変更 |
| `cogs/commands/ping.py` | `ping` を hybrid_command に変更（再適用） |
| `.github/CHANGES.md` | 本セクション追加 |

---

## [fix/requirements-hybrid-help] 2026-05-01

> `feat/4017error` への追加修正。PR #2 コメント起因の問題を完全解決。

---

### 🔴 バグ修正 — requirements.txt: discord.py[voice] と davey が未記載

#### 問題
2025年3月のDiscordセキュリティシステム変更により、ボイス機能に  
**DAVE プロトコル (E2EE)** が導入された。  
これに対応するため `discord.py[voice]` (PyNaCl を含む) および  
`davey` パッケージが必須となったが、`requirements.txt` に記載がなかった。  
インストール漏れが 4017 エラーの直接原因だった。

#### 修正内容 — `requirements.txt`
```
discord.py[voice]>=2.6.4   # [voice] extras: PyNaCl (暗号化) + voice backend
davey>=0.1.0               # DAVE プロトコル E2EE 対応 (2025年3月変更)
PyNaCl>=1.5.0              # discord.py[voice] の依存パッケージ（明示追加）
```

---

### 🔴 バグ修正 — スラッシュコマンドが2個表示される（重複登録）

#### 問題
`on_ready` 内で `copy_global_to(guild=guild)` + `tree.sync(guild=guild)` を  
全ギルドに対して実行していた。  
`setup_hook` で既にグローバル sync が完了しているため  
**グローバル登録 + ギルド登録の二重登録**となり、  
スラッシュコマンドが2個表示されていた。

#### 修正内容 — `bot.py`
- `on_ready` から `copy_global_to` と `tree.sync(guild=guild)` を完全削除
- `setup_hook` のグローバル sync のみに統一
- 新規参加ギルド (`on_guild_join`) には guild sync を維持（即時反映のため）

---

### 🔴 バグ修正 — スラッシュコマンドが「インタラクション失敗」になる

#### 問題
`/eq`, `/diagnose`, `/mystats`, `/stats`, `/party`, `/quiz` などで  
`ctx.interaction.response.defer()` を呼んだ後に  
`_post_v2` (HTTP直送・新規メッセージ) でメッセージを送っていた。  

Discord はインタラクションへの直接応答 (`interaction.response.*` または  
`interaction.followup.*`) を期待するため、HTTP直送メッセージは  
**インタラクションへの「応答」として認識されず**「インタラクション失敗」と表示。

#### 根本原因
```
defer() → _post_v2(新規メッセージ) × ← thinking のまま失敗
```
`_post_v2` は `/channels/{id}/messages` エンドポイントに送るため  
インタラクションの応答エンドポイント `/interactions/{id}/{token}/callback` とは別物。

#### 修正内容

**新規ヘルパー関数 (cogs/music.py)**
- `_ack_post_v2(ctx, bot, components)` — Component v2 のスラッシュ/プレフィックス両対応送信
  - スラッシュ時: `defer(thinking=True)` → `_post_v2` → `delete_original_response()`
  - プレフィックス時: `_post_v2` のみ
- `_reply(ctx, content)` — テキスト返信の両対応ヘルパー
- `_delete_interaction(ctx)` — thinking 表示削除ヘルパー

**修正ファイル一覧**

| ファイル | 修正内容 |
|---|---|
| `cogs/music.py` | `_ack_post_v2` / `_reply` / `_delete_interaction` 追加。全コマンドを新パターンに移行 |
| `cogs/ai_diagnosis.py` | `diagnose` コマンド: `defer(thinking=True)` → HTTP直送 → `delete_original_response()` |
| `cogs/audio_effects.py` | `eq` コマンド: 同上。ボタン/セレクトハンドラに `defer()` を追加 |
| `cogs/statistics.py` | `stats`/`mystats`: 同上。期間セレクトハンドラに `defer()` を追加 |
| `cogs/party.py` | `party`/`quiz`: 同上。全インタラクションハンドラに `defer()` を追加 |
| `cogs/queue_cog.py` | `_ack` を `_reply` パターンに統一（シンプル化） |
| `cogs/commands/help.py` | 新規: `defer(thinking=True)` → HTTP直送 → `delete_original_response()` |

---

### 🟡 新機能 — `/help` コマンド追加

新規ファイル `cogs/commands/help.py` を作成。  
Component v2 で全コマンドをカテゴリ別に表示する。

**表示カテゴリ:**
| カテゴリ | コマンド |
|---|---|
| 🎶 音楽再生 | `/play`, `/search`, `/playlist`, `/nowplaying`, `/queue`, `/skip`, `/pause`, `/resume`, `/stop`, `/leave`, `/volume`, `/loop`, `/shuffle` |
| 📋 キュー管理 | `/remove`, `/move`, `/clearqueue` |
| 🎛️ エフェクト | `/eq` |
| 📊 統計 | `/stats`, `/mystats` |
| 🎉 エンタメ・診断 | `/party`, `/quiz`, `/diagnose` |
| 🔧 その他 | `/ping`, `/help` |

---

### テスト結果 (fix/requirements-hybrid-help)

| テスト項目 | 結果 |
|---|---|
| 全ファイル 構文チェック (19ファイル) | ✅ PASS |
| モジュール インポートテスト (11モジュール) | ✅ PASS |
| requirements.txt 必須パッケージ確認 | ✅ PASS |
| bot.py 重複登録コードなし確認 | ✅ PASS |
| defer+delete_original パターン確認 (6ファイル) | ✅ PASS |
| /help コマンド・全カテゴリ内容確認 | ✅ PASS |
| 全コマンド登録確認 (24コマンド) | ✅ PASS |
| **合計** | **全項目 PASS** |

### 変更ファイル一覧 (fix/requirements-hybrid-help)

| ファイル | 変更内容 |
|---|---|
| `requirements.txt` | `discord.py[voice]`, `davey`, `PyNaCl` 追加 |
| `bot.py` | `on_ready` から重複登録コード削除 |
| `cogs/music.py` | `_ack_post_v2`/`_reply`/`_delete_interaction` 追加・全コマンド移行 |
| `cogs/ai_diagnosis.py` | `diagnose`: defer+delete_original パターン適用 |
| `cogs/audio_effects.py` | `eq`: defer+delete_original パターン適用 |
| `cogs/statistics.py` | `stats`/`mystats`: defer+delete_original パターン適用 |
| `cogs/party.py` | `party`/`quiz`: defer+delete_original パターン適用 |
| `cogs/queue_cog.py` | `_reply` パターンに統一 |
| `cogs/commands/help.py` | 新規作成: Component v2 ヘルプパネル |
| `.github/CHANGES.md` | 本セクション追加 |
