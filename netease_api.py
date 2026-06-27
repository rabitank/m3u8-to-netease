# audience: internal
# netease-api
# 网易云音乐 API 封装 — weapi 加密、二维码登录、搜索、歌单操作。
# 调用前需先实例化 NeteaseAPI，执行 login_qrcode() 完成认证。

import base64
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Optional

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ── 常量 ──────────────────────────────────────────────────
MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b7"
    "25152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0"
    "312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce1"
    "0b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db"
    "0a22b8e7"
)
PUBLIC_KEY = "010001"
IV = "0102030405060708"
PRESET_KEY = "0CoJUm6Qyw8W8jud"
RANDKEY_CHARS = "0123456789abcdeffedcba9876543210"

BASE_URL = "https://music.163.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Origin": "https://music.163.com",
}

COOKIE_FILE = Path.home() / ".m3u8-to-netease-cookie.json"


# ── 加密工具 ──────────────────────────────────────────────

def _aes_encrypt(data: str, key: str) -> str:
    """AES-128-CBC + PKCS7 填充 → base64。"""
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, IV.encode("utf-8"))
    padded = pad(data.encode("utf-8"), AES.block_size)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("utf-8")


def _rsa_encrypt(text: str) -> str:
    """原始 RSA 模幂运算（非 PKCS#1），与网易 JS 端一致。"""
    text_reversed = text[::-1]
    text_hex = text_reversed.encode("utf-8").hex()
    m = int(text_hex, 16)
    e = int(PUBLIC_KEY, 16)
    n = int(MODULUS, 16)
    c = pow(m, e, n)
    return hex(c)[2:].zfill(256)


def _random_key() -> str:
    return "".join(random.choice(RANDKEY_CHARS) for _ in range(16))


def weapi(data: dict[str, Any]) -> dict[str, str]:
    """对 data 做 weapi 加密，返回 {params, encSecKey}。"""
    text = json.dumps(data)
    first = _aes_encrypt(text, PRESET_KEY)
    rk = _random_key()
    params = _aes_encrypt(first, rk)
    enc_sec_key = _rsa_encrypt(rk)
    return {"params": params, "encSecKey": enc_sec_key}


def _eapi_encrypt(path: str, data: dict[str, Any]) -> dict[str, str]:
    """eapi 加密（用于部分接口）。"""
    text = json.dumps(data)
    msg = f"nobody{path}use{text}md5forencrypt"
    sign = hashlib.md5(msg.encode("utf-8")).hexdigest()
    digest = f"{path}-36cd479b6b5-{text}-36cd479b6b5-{sign}"
    return {"params": _aes_encrypt(digest, "e82ckenh8dichen8")}


# ── API 客户端 ────────────────────────────────────────────

class NeteaseAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._uid: int = 0
        self._nickname: str = ""

    @property
    def is_logged_in(self) -> bool:
        return self._uid > 0

    @property
    def nickname(self) -> str:
        return self._nickname

    def _post(self, path: str, data: dict, crypto: str = "weapi") -> dict:
        url = f"{BASE_URL}/{path.lstrip('/')}"
        if crypto == "weapi":
            payload = weapi(data)
        else:
            payload = _eapi_encrypt(path, data)
        resp = self.session.post(
            url,
            data=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 登录 ──────────────────────────────────────────────

    def login_qrcode(self) -> bool:
        """二维码登录。阻塞直到扫描或者超时。"""
        # 获取 unikey
        result = self._post("weapi/login/qrcode/unikey", {"type": 1})
        if result.get("code") != 200:
            print(f"获取二维码 key 失败: {result}")
            return False
        unikey = result["unikey"]

        # 显示二维码
        qr_url = f"https://music.163.com/login?codekey={unikey}"
        self._show_qrcode(qr_url)
        print(f"请用网易云音乐 App 扫描上方二维码登录")
        print(f"或访问: {qr_url}")

        # 轮询登录状态
        for _ in range(120):  # 最多等 2 分钟
            time.sleep(1.5)
            result = self._post(
                "weapi/login/qrcode/client/login",
                {"key": unikey, "type": 1},
            )
            code = result.get("code")
            if code == 803:
                # 登录成功，cookie 已由 session 保存
                self._extract_user_info()
                self._save_cookie()
                return True
            elif code == 800:
                print("二维码已过期，请重试")
                return False
            elif code == 801:
                pass  # 等待扫码
            elif code == 802:
                print("已扫码，请在手机上确认登录...")
            else:
                print(f"未知状态码: {code} {result}")
        print("登录超时")
        return False

    def login_cookie(self, cookie_str: str) -> bool:
        """通过 cookie 字符串登录。"""
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip())
        result = self._post("weapi/w/nuser/account/get", {})
        if result.get("code") == 200:
            profile = result.get("profile", {})
            self._uid = profile.get("userId", 0)
            self._nickname = profile.get("nickname", "")
            self._save_cookie()
            return True
        return False

    def _extract_user_info(self):
        try:
            result = self._post("weapi/w/nuser/account/get", {})
            if result.get("code") == 200:
                profile = result.get("profile", {})
                self._uid = profile.get("userId", 0)
                self._nickname = profile.get("nickname", "")
        except Exception:
            pass

    def try_auto_login(self) -> bool:
        """尝试用本地保存的 cookie 自动登录。"""
        if not COOKIE_FILE.exists():
            return False
        try:
            saved = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            for k, v in saved.items():
                self.session.cookies.set(k, v)
            self._extract_user_info()
            return self.is_logged_in
        except Exception:
            return False

    def _save_cookie(self):
        cookies = self.session.cookies.get_dict()
        COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _show_qrcode(url: str):
        """终端打印二维码（URL + ASCII 艺术）。"""
        print(f"登录二维码 URL: {url}")
        try:
            import qrcode
            import io

            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            buf = io.StringIO()
            qr.print_ascii(out=buf, invert=False)
            print(buf.getvalue(), end="")
        except Exception:
            pass

    # ── 搜索 ──────────────────────────────────────────────

    def search_song(self, keywords: str, limit: int = 5) -> list[dict]:
        """搜索歌曲，返回歌曲列表。"""
        result = self._post(
            "weapi/cloudsearch/get/web",
            {"s": keywords, "type": 1, "limit": limit, "offset": 0},
        )
        if result.get("code") == 200:
            return result.get("result", {}).get("songs", [])
        return []

    # ── 歌单操作 ──────────────────────────────────────────

    def create_playlist(self, name: str, privacy: int = 0) -> Optional[int]:
        """
        创建歌单。privacy: 0=公开, 10=私密。
        返回 playlist_id，失败返回 None。
        """
        result = self._post(
            "weapi/playlist/create",
            {"name": name, "privacy": privacy},
        )
        if result.get("code") == 200:
            pid = result.get("id", 0)
            print(f"歌单创建成功，ID: {pid}")
            return pid
        print(f"创建歌单失败: {result}")
        return None

    def add_tracks(self, playlist_id: int, track_ids: list[int]) -> int:
        """
        向歌单添加歌曲。支持最多 1000 首/次。
        返回成功添加的数量。
        """
        tracks_str = ",".join(str(tid) for tid in track_ids)
        result = self._post(
            "weapi/playlist/tracks",
            {"op": "add", "pid": playlist_id, "tracks": tracks_str},
        )
        if result.get("code") == 200:
            return result.get("count", 0)
        print(f"添加歌曲失败: {result}")
        return 0

    def get_playlist_link(self, playlist_id: int) -> str:
        return f"https://music.163.com/playlist?id={playlist_id}"
