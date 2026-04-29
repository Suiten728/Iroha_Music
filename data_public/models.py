"""
data/models.py — SQLite 非同期データベースラッパー
aiosqlite を使用して Guild設定・音楽統計・AI診断・センシティブキャッシュを管理する
"""

from __future__ import annotations

import logging
import aiosqlite

log = logging.getLogger("iroha.db")

DB_PATH = "iroha.db"

# ─── テーブル定義 SQL ──────────────────────────────────────────────────

_INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id          INTEGER PRIMARY KEY,
    prefix            TEXT    DEFAULT 'IM!',
    music_channel_id  INTEGER DEFAULT NULL,
    max_queue         INTEGER DEFAULT 200,
    auto_leave_sec    INTEGER DEFAULT 300,
    sensitive_warn    INTEGER DEFAULT 1,
    updated_at        TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audio_settings (
    guild_id    INTEGER PRIMARY KEY,
    preset      TEXT    DEFAULT 'flat',
    bass_boost  INTEGER DEFAULT 0,
    surround    INTEGER DEFAULT 0,
    reverb      INTEGER DEFAULT 0,
    eq_bands    TEXT    DEFAULT '{}',
    updated_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS music_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    url         TEXT    NOT NULL DEFAULT '',
    duration    INTEGER DEFAULT 0,
    played_at   TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_profiles (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    music_type    TEXT    NOT NULL,
    energy_score  REAL    DEFAULT 0.5,
    genre_scores  TEXT    DEFAULT '{}',
    updated_at    TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS sensitive_cache (
    url        TEXT PRIMARY KEY,
    flags      TEXT DEFAULT '[]',
    cached_at  TEXT DEFAULT (datetime('now'))
);
"""


class Database:
    """aiosqlite ラッパー — fetchone / fetchall / execute / commit を提供する"""

    def __init__(self, path: str = DB_PATH) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """データベース接続を開きテーブルを初期化する"""
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_INIT_SQL)
        await self._conn.commit()
        log.info(f"Database initialized: {self._path}")

    async def close(self) -> None:
        """接続を閉じる"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            log.info("Database connection closed.")

    # ── 基本操作 ─────────────────────────────────────────────────────────

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        """INSERT / UPDATE / DELETE などを実行する"""
        if self._conn is None:
            raise RuntimeError("Database.init() を先に呼び出してください。")
        return await self._conn.execute(sql, params)

    async def executemany(self, sql: str, params_list: list[tuple]) -> None:
        """バルクINSERT / UPDATE"""
        if self._conn is None:
            raise RuntimeError("Database.init() を先に呼び出してください。")
        await self._conn.executemany(sql, params_list)

    async def commit(self) -> None:
        """トランザクションをコミットする"""
        if self._conn is None:
            raise RuntimeError("Database.init() を先に呼び出してください。")
        await self._conn.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        """1行取得。結果がなければ None を返す"""
        if self._conn is None:
            raise RuntimeError("Database.init() を先に呼び出してください。")
        async with self._conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        """全行取得"""
        if self._conn is None:
            raise RuntimeError("Database.init() を先に呼び出してください。")
        async with self._conn.execute(sql, params) as cur:
            return await cur.fetchall()