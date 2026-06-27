# audience: internal
# matcher
# 将解析出的歌曲信息与网易云搜索结果匹配，返回最佳候选。

from difflib import SequenceMatcher
from typing import Optional


def similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0~1)。"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _get_artists(song: dict) -> list[str]:
    """从 API 搜索结果中提取歌手名列表，兼容 ar / artists 字段。"""
    ar = song.get("ar") or song.get("artists", [])
    return [a.get("name", "") for a in ar if a.get("name")]


def _format_song(song: dict) -> str:
    """从 API 搜索结果中提取 "歌手 - 歌名"。"""
    name = song.get("name", "")
    artists = "/".join(_get_artists(song))
    return f"{artists} - {name}"


def match_song(
    artist: str,
    title: str,
    search_results: list[dict],
    threshold: float = 0.75,
) -> Optional[tuple[dict, float]]:
    """
    从搜索结果中匹配最佳歌曲。

    匹配策略:
      1. 对 artist+title 组合计算相似度
      2. 加权: 歌名权重高于歌手名
      3. 返回 (song_dict, confidence) 或 None

    参数:
      threshold: 最低置信度，低于此值视为无匹配
    """
    if not search_results:
        return None

    best_song: Optional[dict] = None
    best_score = 0.0

    for song in search_results:
        song_name = song.get("name", "")
        song_artists = "/".join(_get_artists(song))

        # 歌名相似度 (权重 0.6) + 歌手相似度 (权重 0.4)
        title_sim = similarity(title, song_name)
        artist_sim = similarity(artist, song_artists)
        score = title_sim * 0.6 + artist_sim * 0.4

        if score > best_score:
            best_score = score
            best_song = song

    if best_song is None or best_score < threshold:
        return None

    return (best_song, best_score)
