# 🎵 いろは Music System

> **次世代型AI診断 × 高度音響処理対応 Discord音楽Bot**
> OSS / MIT License / マルチサーバー対応

---

## 🌟 特徴

| 機能 | 説明 |
|------|------|
| 🎵 高品質再生 | yt-dlp + FFmpeg による高音質ストリーミング |
| 🤖 AI診断 | 3問診断で個人の音楽タイプを分析・キュー自動生成 |
| 🎛️ イコライザー | Guild別EQ設定、5種プリセット、Bass Boost、立体音響 |
| ⚠️ センシティブ警告 | 性的・暴力・鬱的表現の事前検知と確認UI |
| 📊 統計分析 | 月間ランキング、ユーザー別統計、活動時間帯分析 |
| 🎉 パーティーモード | DJ交代制、盛り上がりスコア、曲当てクイズ |
| 🖥️ Component v2 UI | LayoutView / IS_COMPONENTS_V2 を全面採用 |

---

## ⚙️ セットアップ

### 必要環境

- Python 3.11+
- FFmpeg（PATH が通っていること）
- Discord Bot Token

### インストール

```bash
# リポジトリのクローン
git clone https://github.com/yourname/iroha-music-bot.git
cd iroha-music-bot

# 依存パッケージのインストール
pip install -r requirements.txt

# FFmpeg のインストール（未導入の場合）
# Ubuntu/Debian:
sudo apt install ffmpeg

# macOS:
brew install ffmpeg

# Windows:
# https://ffmpeg.org/download.html からダウンロードしてPATHに追加
```

### 設定

```bash
# 環境変数ファイルをコピー
cp .env.example .env

# .env を編集してトークンを設定
DISCORD_TOKEN=your_discord_bot_token_here
```

### Discord Developer Portal 設定

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. アプリケーションを作成 → Bot セクション
3. **Privileged Gateway Intents** を全て有効化
   - `SERVER MEMBERS INTENT`
   - `MESSAGE CONTENT INTENT`
4. OAuth2 → URL Generator で `bot` + `applications.commands` スコープを選択
5. Bot Permissions: `Connect`, `Speak`, `Send Messages`, `Read Message History`, `Use Slash Commands`

### 起動

```bash
python bot.py
```

---

## 📋 コマンド一覧

### 🎵 音楽再生

| コマンド | 説明 |
|----------|------|
| `!play <URL or 検索ワード>` | 曲を再生する |
| `!search <検索ワード>` | 検索して選択UIを表示 |
| `!playlist <URL>` | プレイリストを丸ごと追加 |
| `!pause` | 一時停止 |
| `!resume` | 再開 |
| `!stop` | 停止（キュークリア） |
| `!skip` | スキップ（投票スキップ） |
| `!volume <1-150>` | 音量設定 |
| `!loop <none/one/all>` | ループ設定 |
| `!shuffle` | シャッフルON/OFF |
| `!leave` | ボイスチャンネルから切断 |

### 📋 キュー管理

| コマンド | 説明 |
|----------|------|
| `!queue` | キュー一覧表示（ページネーション付き） |
| `!nowplaying` | 現在の曲を表示 |
| `!remove <番号>` | 指定曲を削除 |
| `!move <from> <to>` | 曲を移動 |
| `!clearqueue` | キューを全クリア |

### 🤖 AI診断

| コマンド | 説明 |
|----------|------|
| `!diagnose` | AI音楽診断を開始（3問） |

### 🎛️ オーディオエフェクト

| コマンド | 説明 |
|----------|------|
| `!eq` | イコライザーパネルを表示 |

**プリセット一覧:**
- 🎵 Flat（デフォルト）
- 🔊 Bass Boost
- 🎤 Vocal Clear
- 🌐 3D Surround
- 🏟️ Live Hall
- 🌙 Night Mode

### 📊 統計

| コマンド | 説明 |
|----------|------|
| `!stats` | サーバーの月間統計を表示 |
| `!mystats` | 自分の再生履歴を表示 |

### 🎉 パーティー・エンタメ

| コマンド | 説明 |
|----------|------|
| `!party` | パーティーモードパネルを表示 |
| `!quiz` | 曲当てクイズを開始 |

---

## 🏗️ プロジェクト構成

```
iroha_music/
├── bot.py                    # Bot エントリーポイント
├── requirements.txt
├── .env.example
│
├── cogs/                     # 機能モジュール
│   ├── music.py              # 再生・コントロール
│   ├── queue_cog.py          # キュー管理
│   ├── ai_diagnosis.py       # AI診断システム
│   ├── audio_effects.py      # EQ・エフェクト
│   ├── statistics.py         # 統計・ランキング
│   ├── party.py              # パーティー・クイズ
│   └── sensitive_filter.py  # センシティブ検知
│
├── core/                     # コアシステム
│   ├── guild_manager.py      # Guild別状態管理
│   ├── config_loader.py      # 設定読み込み
│   └── logger.py             # ロギング
│
├── utils/                    # ユーティリティ
│   ├── audio_engine.py       # yt-dlp・FFmpegフィルター
│   ├── ai_engine.py          # 診断アルゴリズム
│   └── filter_engine.py      # センシティブ検知ロジック
│
└── data/                     # データ層
    ├── models.py             # Database クラス
    └── schema.sql            # テーブル定義
```

---

## 🗄️ データベース設計

全テーブルに `guild_id` を持ちマルチサーバーを完全分離。

| テーブル | 用途 |
|----------|------|
| `guild_settings` | Guild別設定（音量・センシティブ警告・自動退出等） |
| `music_stats` | 再生履歴・統計 |
| `ai_profiles` | AI診断結果の保存 |
| `audio_settings` | EQ・エフェクト設定 |
| `party_sessions` | パーティーモード状態 |
| `sensitive_cache` | センシティブスキャンキャッシュ |

---

## 🖥️ UI設計 — Component v2 (LayoutView)

本プロジェクトは **discord.py 2.6.4** の **Component v2 / IS_COMPONENTS_V2** を全面採用。

### 採用した主要パターン

**1. JSON直送方式（動的コンテンツ）**
```python
await bot.http.request(
    discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ch.id),
    json={"flags": 1 << 15, "components": build_components()},
)
```

**2. NoCopy ミックスイン（cog保持コンポーネント）**
```python
class NoCopy:
    def __deepcopy__(self, memo):
        return self

class MyButton(NoCopy, discord.ui.Button):
    def __init__(self, cog): ...
```

**3. Persistent View（bot再起動後も動作）**
```python
async def on_ready(self):
    self.bot.add_view(MyPersistentView(self))
```

---

## 🤝 コントリビュート

1. このリポジトリをフォーク
2. feature ブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add amazing feature'`)
4. プッシュ (`git push origin feature/amazing-feature`)
5. Pull Request を作成

**コード規約:** PEP8準拠 / type hints 推奨 / docstring 必須

---

## 📄 ライセンス

MIT License — 詳細は [LICENSE](LICENSE) を参照

---

## 🚀 ロードマップ

- [ ] Webダッシュボード（FastAPI + Next.js）
- [ ] Lavalink 対応
- [ ] Spotify 連携
- [ ] 多言語対応（i18n）
- [ ] Docker対応
