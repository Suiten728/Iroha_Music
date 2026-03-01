"""
utils/ai_engine.py — AI音楽診断エンジン
3問ランダム出題 → スコア算出 → 楽曲タイプ分類
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass

# ─── 診断設問定義 ───────────────────────────────────────────────────

QUESTIONS: list[dict] = [
    # ── ジャンル系 ──────────────────────────────────────────
    {
        "id": "g1",
        "category": "genre",
        "text": "好きな音楽の雰囲気は？",
        "options": [
            {"label": "激しくてエネルギッシュ", "value": "g1a", "genre_boost": {"rock": 0.3, "metal": 0.2, "edm": 0.2}},
            {"label": "リズミカルでノリノリ", "value": "g1b", "genre_boost": {"pop": 0.3, "hiphop": 0.2, "edm": 0.15}},
            {"label": "メロディアスで聴きやすい", "value": "g1c", "genre_boost": {"pop": 0.25, "acoustic": 0.25, "jazz": 0.1}},
            {"label": "深みがあってムーディー", "value": "g1d", "genre_boost": {"jazz": 0.3, "rnb": 0.25, "acoustic": 0.1}},
        ],
    },
    {
        "id": "g2",
        "category": "genre",
        "text": "ライブに行くなら？",
        "options": [
            {"label": "フェス・野外ロック", "value": "g2a", "genre_boost": {"rock": 0.35, "edm": 0.15}},
            {"label": "クラブ・ダンスイベント", "value": "g2b", "genre_boost": {"edm": 0.35, "hiphop": 0.2}},
            {"label": "ホール・コンサート", "value": "g2c", "genre_boost": {"classical": 0.3, "pop": 0.2}},
            {"label": "小さなライブハウス", "value": "g2d", "genre_boost": {"acoustic": 0.3, "jazz": 0.2}},
        ],
    },
    # ── 気分系 ──────────────────────────────────────────────
    {
        "id": "m1",
        "category": "mood",
        "text": "今の気分は？",
        "options": [
            {"label": "ハイテンション！", "value": "m1a", "energy_boost": 0.9, "genre_boost": {"rock": 0.2, "edm": 0.3}},
            {"label": "そこそこ元気", "value": "m1b", "energy_boost": 0.6, "genre_boost": {"pop": 0.25}},
            {"label": "まったりしたい", "value": "m1c", "energy_boost": 0.3, "genre_boost": {"acoustic": 0.2, "jazz": 0.2}},
            {"label": "落ち着きたい", "value": "m1d", "energy_boost": 0.1, "genre_boost": {"classical": 0.2, "ambient": 0.3}},
        ],
    },
    {
        "id": "m2",
        "category": "mood",
        "text": "音楽を聴くシチュエーションは？",
        "options": [
            {"label": "運動・ワークアウト", "value": "m2a", "energy_boost": 0.9, "genre_boost": {"rock": 0.2, "edm": 0.25, "hiphop": 0.2}},
            {"label": "友人と盛り上がる", "value": "m2b", "energy_boost": 0.7, "genre_boost": {"pop": 0.3, "hiphop": 0.2}},
            {"label": "集中・作業BGM", "value": "m2c", "energy_boost": 0.4, "genre_boost": {"ambient": 0.3, "jazz": 0.2}},
            {"label": "1人でゆっくり", "value": "m2d", "energy_boost": 0.2, "genre_boost": {"acoustic": 0.3, "classical": 0.2}},
        ],
    },
    # ── エネルギー系 ─────────────────────────────────────────
    {
        "id": "e1",
        "category": "energy",
        "text": "テンポの好みは？",
        "options": [
            {"label": "速い！アップテンポ大好き", "value": "e1a", "energy_boost": 0.85, "genre_boost": {"edm": 0.25, "rock": 0.25}},
            {"label": "ミドルテンポが気持ちいい", "value": "e1b", "energy_boost": 0.55, "genre_boost": {"pop": 0.3}},
            {"label": "スローでじっくり", "value": "e1c", "energy_boost": 0.25, "genre_boost": {"rnb": 0.25, "acoustic": 0.2}},
            {"label": "曲による", "value": "e1d", "energy_boost": 0.5, "genre_boost": {}},
        ],
    },
    {
        "id": "e2",
        "category": "energy",
        "text": "ベースやドラムが強い曲は好き？",
        "options": [
            {"label": "大好き！ドンドン鳴らして", "value": "e2a", "energy_boost": 0.8, "genre_boost": {"edm": 0.3, "hiphop": 0.2}},
            {"label": "ほどほどなら好き", "value": "e2b", "energy_boost": 0.5, "genre_boost": {"pop": 0.2}},
            {"label": "あまり好きじゃない", "value": "e2c", "energy_boost": 0.3, "genre_boost": {"acoustic": 0.2, "classical": 0.15}},
            {"label": "気にしない", "value": "e2d", "energy_boost": 0.5, "genre_boost": {}},
        ],
    },
    # ── ライフスタイル系 ──────────────────────────────────────
    {
        "id": "l1",
        "category": "lifestyle",
        "text": "週末の過ごし方は？",
        "options": [
            {"label": "外で活発に動く", "value": "l1a", "energy_boost": 0.75, "genre_boost": {"rock": 0.2, "pop": 0.2}},
            {"label": "友人と賑やかに", "value": "l1b", "energy_boost": 0.65, "genre_boost": {"pop": 0.25, "hiphop": 0.15}},
            {"label": "カフェや読書でのんびり", "value": "l1c", "energy_boost": 0.3, "genre_boost": {"jazz": 0.25, "acoustic": 0.2}},
            {"label": "家でゴロゴロ", "value": "l1d", "energy_boost": 0.15, "genre_boost": {"ambient": 0.25, "acoustic": 0.15}},
        ],
    },
    {
        "id": "l2",
        "category": "lifestyle",
        "text": "音楽のリリックについて",
        "options": [
            {"label": "歌詞は重要！刺さる言葉が好き", "value": "l2a", "genre_boost": {"jpop": 0.3, "acoustic": 0.2}},
            {"label": "ビートとリズムを重視", "value": "l2b", "genre_boost": {"hiphop": 0.25, "edm": 0.25}},
            {"label": "インストが好き", "value": "l2c", "genre_boost": {"jazz": 0.25, "classical": 0.25, "ambient": 0.2}},
            {"label": "どちらでもOK", "value": "l2d", "genre_boost": {}},
        ],
    },
]

# 音楽タイプ分類
MUSIC_TYPES: dict[str, dict] = {
    "high_energy_rock": {
        "label": "⚡ ハイエナジー・ロッカー",
        "description": "激しいビートと歪んだギターで魂を燃やすタイプ",
        "primary_genres": ["rock", "metal", "edm"],
        "energy_range": (0.7, 1.0),
    },
    "dance_floor_king": {
        "label": "💃 ダンスフロアの支配者",
        "description": "リズムとビートで場を支配する踊り出したいタイプ",
        "primary_genres": ["edm", "hiphop", "pop"],
        "energy_range": (0.6, 1.0),
    },
    "chill_vibes": {
        "label": "😌 チルアウト探求者",
        "description": "穏やかなメロディと落ち着いた空間を愛するタイプ",
        "primary_genres": ["acoustic", "jazz", "ambient"],
        "energy_range": (0.0, 0.45),
    },
    "pop_lover": {
        "label": "🌟 ポップス大好き人間",
        "description": "キャッチーなメロディと聴きやすいサウンドが好きなタイプ",
        "primary_genres": ["pop", "jpop", "rnb"],
        "energy_range": (0.4, 0.7),
    },
    "jazz_soul": {
        "label": "🎷 ジャズ・ソウル愛好家",
        "description": "深みとグルーヴを重視する感性豊かなタイプ",
        "primary_genres": ["jazz", "rnb", "acoustic"],
        "energy_range": (0.2, 0.6),
    },
    "classical_aesthetic": {
        "label": "🎻 クラシカル審美家",
        "description": "構造美と感情表現を音楽に求める芸術的タイプ",
        "primary_genres": ["classical", "ambient"],
        "energy_range": (0.0, 0.5),
    },
}

GENRE_SEARCH_QUERIES: dict[str, list[str]] = {
    "rock": ["rock playlist 2024", "classic rock best hits", "alternative rock"],
    "metal": ["heavy metal playlist", "metal hits", "metalcore playlist"],
    "edm": ["edm playlist 2024", "electronic dance music", "house music playlist"],
    "hiphop": ["hip hop playlist 2024", "rap hits", "trap music playlist"],
    "pop": ["pop hits 2024", "top pop songs", "pop playlist"],
    "jpop": ["jpop playlist 2024", "japanese pop hits", "j-pop best songs"],
    "acoustic": ["acoustic playlist", "acoustic guitar songs", "indie acoustic"],
    "jazz": ["jazz playlist", "smooth jazz", "jazz chill"],
    "rnb": ["rnb playlist 2024", "r&b hits", "neo soul playlist"],
    "classical": ["classical music playlist", "orchestral music", "piano classics"],
    "ambient": ["ambient playlist", "lo-fi chill beats", "ambient study music"],
}


@dataclass
class DiagnosisResult:
    music_type: str
    type_label: str
    type_description: str
    energy_score: float
    genre_scores: dict[str, float]
    top_genres: list[str]
    search_queries: list[str]


def pick_questions(n: int = 3) -> list[dict]:
    """カテゴリ偏り防止のバランス抽出"""
    categories = ["genre", "mood", "energy", "lifestyle"]
    selected: list[dict] = []
    by_cat: dict[str, list] = {c: [] for c in categories}
    for q in QUESTIONS:
        by_cat[q["category"]].append(q)

    # 各カテゴリから1問ずつ取り、残りはランダムで補充
    pool: list[dict] = []
    for cat in categories:
        if by_cat[cat]:
            pool.append(random.choice(by_cat[cat]))

    random.shuffle(pool)
    selected = pool[:n]
    return selected


def calculate_result(answers: list[dict]) -> DiagnosisResult:
    """
    回答リスト [{question_id, option_value, option_data}, ...] から診断結果を算出
    """
    genre_scores: dict[str, float] = {}
    energy_scores: list[float] = []

    for ans in answers:
        opt = ans.get("option_data", {})
        # エネルギースコア
        if "energy_boost" in opt:
            energy_scores.append(opt["energy_boost"])
        # ジャンルスコア
        for genre, boost in opt.get("genre_boost", {}).items():
            genre_scores[genre] = genre_scores.get(genre, 0) + boost

    # 平均エネルギー
    energy_score = sum(energy_scores) / len(energy_scores) if energy_scores else 0.5

    # ジャンルスコア正規化（0~1）
    max_score = max(genre_scores.values()) if genre_scores else 1
    normalized = {g: round(v / max_score, 3) for g, v in genre_scores.items()}

    # 上位ジャンル
    top_genres = sorted(normalized, key=lambda g: normalized[g], reverse=True)[:3]

    # 音楽タイプ分類
    music_type_key = _classify_type(energy_score, top_genres)
    mtype = MUSIC_TYPES[music_type_key]

    # 検索クエリ生成
    queries: list[str] = []
    for g in top_genres:
        q_list = GENRE_SEARCH_QUERIES.get(g, [])
        if q_list:
            queries.append(random.choice(q_list))

    return DiagnosisResult(
        music_type=music_type_key,
        type_label=mtype["label"],
        type_description=mtype["description"],
        energy_score=round(energy_score, 3),
        genre_scores=normalized,
        top_genres=top_genres,
        search_queries=queries[:3],
    )


def _classify_type(energy: float, top_genres: list[str]) -> str:
    """エネルギーとジャンルからタイプを分類"""
    genre_set = set(top_genres)
    if energy >= 0.7 and genre_set & {"rock", "metal"}:
        return "high_energy_rock"
    if energy >= 0.6 and genre_set & {"edm", "hiphop"}:
        return "dance_floor_king"
    if energy <= 0.4 and genre_set & {"acoustic", "ambient"}:
        return "chill_vibes"
    if genre_set & {"jazz", "rnb"}:
        return "jazz_soul"
    if genre_set & {"classical"}:
        return "classical_aesthetic"
    return "pop_lover"
