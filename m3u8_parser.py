# audience: internal
# m3u8-parser
# 解析 .m3u8 播放列表，提取歌曲元信息。

from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass
class Track:
    artist: str
    title: str
    duration: float
    filepath: str
    index: int
    raw_line: str = field(repr=False)

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


# 常见分隔符: " - ", " / ", " – " (en dash)
SEP_PATTERN = re.compile(r"\s*[-–/]\s*")


def _parse_extinf_title(raw: str) -> tuple[str, str]:
    """从 EXTINF 标题行解析 (歌手, 歌名)。"""
    raw = raw.strip()
    if not raw:
        return ("未知歌手", "未知歌名")

    parts = SEP_PATTERN.split(raw, maxsplit=1)
    if len(parts) == 2:
        return (parts[0].strip(), parts[1].strip())
    return ("未知歌手", parts[0].strip())


def _infer_from_path(filepath: str) -> tuple[str, str]:
    """当 EXTINF 无标题时，从文件路径名推断。"""
    name = Path(filepath).stem
    parts = SEP_PATTERN.split(name, maxsplit=1)
    if len(parts) == 2:
        return (parts[0].strip(), parts[1].strip())
    return ("未知歌手", name.strip())


def parse_m3u8(filepath: str) -> list[Track]:
    """解析 .m3u8 文件，返回 Track 列表。"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    content = path.read_text(encoding="utf-8-sig")
    lines = content.splitlines()

    tracks: list[Track] = []
    index = 0
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line or line == "#EXTM3U":
            i += 1
            continue
        if line.startswith("#EXTINF"):
            duration = 0.0
            title_raw = ""
            comma_pos = line.find(",")
            if comma_pos != -1:
                dur_str = line[8:comma_pos]
                try:
                    duration = float(dur_str)
                except ValueError:
                    duration = 0.0
                title_raw = line[comma_pos + 1 :]
            # 找下一行的路径/URL
            filepath_str = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line.startswith("#"):
                    filepath_str = next_line
                    i += 1  # 跳过文件路径行
            artist, title = _parse_extinf_title(title_raw)
            if not title_raw and filepath_str:
                artist, title = _infer_from_path(filepath_str)
            tracks.append(
                Track(
                    artist=artist,
                    title=title,
                    duration=duration,
                    filepath=filepath_str,
                    index=index,
                    raw_line=line,
                )
            )
            index += 1
        elif not line.startswith("#"):
            # 无 EXTINF 的直接路径行
            artist, title = _infer_from_path(line)
            tracks.append(
                Track(
                    artist=artist,
                    title=title,
                    duration=0.0,
                    filepath=line,
                    index=index,
                    raw_line=line,
                )
            )
            index += 1
        i += 1

    return tracks
