# audience: internal
# netease-api
# 网易云音乐 API 客户端 — 对接本地 NeteaseCloudMusicApi 服务。
# 所有加密/登录逻辑由 Node.js API 服务处理，本模块仅做 HTTP 调用。

import base64
import json
import time
from pathlib import Path
from typing import Any, Optional

import requests

COOKIE_FILE = Path.home() / ".m3u8-to-netease-cookie.json"


class NeteaseAPI:
    """网易云 API 客户端。"""

    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url.rstrip("/")
        self.cookie: str = ""
        self._uid: int = 0
        self._nickname: str = ""

    @property
    def is_logged_in(self) -> bool:
        return self._uid > 0

    @property
    def nickname(self) -> str:
        return self._nickname

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """GET 请求，自动从响应头和 JSON Body 中提取 Set-Cookie 并刷新。"""
        if params is None:
            params = {}
        headers = {}
        if self.cookie:
            headers["Cookie"] = self.cookie
        resp = requests.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        self._refresh_cookie(resp, result)
        return result

    def _call(self, path: str, data: dict[str, Any] | None = None) -> dict:
        """POST 请求（fallback），含 cookie 刷新。"""
        if data is None:
            data = {}
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        resp = requests.post(
            f"{self.base_url}{path}",
            json=data,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        self._refresh_cookie(resp, result)
        return result

    def _refresh_cookie(self, resp: requests.Response, result: dict):
        """从 HTTP 响应头及 JSON body 中提取更新的 cookie。保留原始大小写。"""
        old = self.cookie
        # 用小写做索引，保留原始 case 值
        current: dict[str, str] = {}   # lowercase → original_case
        values: dict[str, str] = {}    # original_case → value
        if self.cookie:
            for pair in self.cookie.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    k_orig = k.strip()
                    current[k_orig.lower()] = k_orig
                    values[k_orig] = v.strip()

        def _feed(raw: str):
            for segment in raw.replace(";;", ";").split(";"):
                segment = segment.strip()
                if not segment or "=" not in segment:
                    continue
                k, v = segment.split("=", 1)
                k_lower = k.strip().lower()
                if k_lower in ("max-age", "expires", "path", "domain",
                               "secure", "httponly", "samesite"):
                    continue
                k_orig = k.strip()
                current[k_lower] = k_orig
                values[k_orig] = v.strip()

        # HTTP Set-Cookie 头
        set_cookie = resp.headers.get("set-cookie", "")
        if set_cookie:
            _feed(set_cookie)

        # JSON body 中的 cookie 数组
        body_cookie = result.get("cookie", [])
        if isinstance(body_cookie, str):
            body_cookie = [body_cookie]
        for c in body_cookie:
            if isinstance(c, str):
                _feed(c)

        self.cookie = "; ".join(f"{k}={values[k]}" for k in current.values())
        if self.cookie != old:
            self._save_cookie()

    @staticmethod
    def _clean_cookie(raw: str) -> str:
        """将 Set-Cookie 响应格式清洗为 Cookie 请求头格式。
        剥离 Max-Age/Expires/Path/Domain 等属性，保留原始大小写。"""
        skip = {"max-age", "expires", "path", "domain", "secure", "httponly", "samesite"}
        seen: set[str] = set()
        result_pairs: list[str] = []
        for segment in raw.replace(";;", ";").split(";"):
            segment = segment.strip()
            if not segment or "=" not in segment:
                continue
            k, v = segment.split("=", 1)
            k_lower = k.strip().lower()
            if k_lower in skip:
                continue
            if k_lower in seen:
                continue
            seen.add(k_lower)
            result_pairs.append(f"{k.strip()}={v.strip()}")
        return "; ".join(result_pairs)

    def login_qrcode(self) -> bool:
        """二维码登录。返回二维码 URL，轮询直到扫描成功。"""
        # 1. 获取 unikey
        result = self._get("/login/qr/key", {"timerstamp": int(time.time() * 1000)})
        data = result.get("data", result)
        if not data.get("unikey"):
            print(f"获取二维码 key 失败: {result}")
            return False
        unikey = data["unikey"]

        # 2. 生成二维码
        qr_result = self._get(
            "/login/qr/create",
            {"key": unikey, "qrimg": "true", "timerstamp": int(time.time() * 1000)},
        )
        qr_data = qr_result.get("data", qr_result)
        qr_url = qr_data.get("qrurl", "")
        qrimg_b64 = qr_data.get("qrimg", "")

        print("\n" + "=" * 50)
        self._show_qrcode(qr_url, qrimg_b64)
        print("=" * 50)
        print("用网易云音乐手机 App 扫描上方二维码登录")
        print("（不是浏览器打开！是 App 首页左上角扫码）")
        print(f"备用: 复制此链接到手机浏览器 → 自动跳转 App 登录")
        print(f"      {qr_url}")
        print("=" * 50)

        # 3. 轮询登录状态
        retries = 120
        for i in range(retries):
            time.sleep(1.5)
            check = self._get(
                "/login/qr/check",
                {"key": unikey, "timerstamp": int(time.time() * 1000)},
            )
            code = check.get("code")
            if code == 803:
                cookie = check.get("cookie", "")
                if cookie:
                    self.cookie = self._clean_cookie(cookie)
                    self._extract_user_info()
                    self._save_cookie()
                    return True
                print("登录成功但未获取到 cookie")
                return False
            elif code == 800:
                print("二维码已过期，请重试")
                return False
            elif code == 801:
                if i % 20 == 0 and i > 0:
                    print(f"  等待扫码... ({i * 1.5:.0f}s)")
            elif code == 802:
                print("  已扫码，请在手机上确认登录...")
            else:
                print(f"  服务器返回异常: code={code} {check.get('message', '')}")
                break
        print("登录超时（2分钟），请重试")
        return False

    def login_phone(self, phone: str, password: str = "", countrycode: str = "86") -> bool:
        """手机号登录。使用 POST 避免密码出现在 URL 中。"""
        if not password:
            return self._login_phone_captcha(phone, countrycode)

        try:
            result = self._call(
                "/login/cellphone",
                {
                    "phone": phone,
                    "password": password,
                    "countrycode": countrycode,
                },
            )
            return self._handle_login_result(result)
        except Exception as e:
            msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    body = e.response.json()
                    msg = body.get("message") or body.get("msg") or msg
                except Exception:
                    pass
            print(f"手机登录失败: {msg}")
            return False

    def _login_phone_captcha(self, phone: str, countrycode: str) -> bool:
        """短信验证码登录。"""
        send = self._call(
            "/captcha/sent",
            {"phone": phone, "ctcode": countrycode},
        )
        if send.get("code") != 200:
            print(f"发送验证码失败: {send.get('message', send)}")
            return False
        print("验证码已发送，请查收短信")
        captcha = input("输入短信验证码: ").strip()
        if not captcha:
            return False
        result = self._call(
            "/login/cellphone",
            {
                "phone": phone,
                "captcha": captcha,
                "countrycode": countrycode,
            },
        )
        return self._handle_login_result(result)

    def _handle_login_result(self, result: dict) -> bool:
        cookie = result.get("cookie", "")
        if cookie:
            self.cookie = self._clean_cookie(cookie)
            self._extract_user_info()
            self._save_cookie()
            return True
        code = result.get("code")
        msg = result.get("message", "")
        if code == 501:
            print("需要短信验证码")
        elif code == 502:
            print("需要验证码")
        elif code == 400:
            print(f"参数错误: {msg}")
        elif code == 200:
            print("登录成功，但未获取到 cookie")
        else:
            print(f"登录失败 [{code}]: {msg}")
        return False

    def login_cookie(self, cookie_str: str) -> bool:
        """直接使用 cookie 字符串登录。"""
        self.cookie = self._clean_cookie(cookie_str.strip())
        try:
            self._extract_user_info()
            if self.is_logged_in:
                self._save_cookie()
                return True
        except Exception:
            pass
        print("Cookie 无效或已过期")
        return False

    def try_auto_login(self) -> bool:
        """尝试用本地保存的 cookie 自动登录。"""
        if not COOKIE_FILE.exists():
            return False
        try:
            saved = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, str):
                self.cookie = self._clean_cookie(saved)
            elif isinstance(saved, dict):
                self.cookie = self._clean_cookie(
                    "; ".join(f"{k}={v}" for k, v in saved.items())
                )
            self._extract_user_info()
            return self.is_logged_in
        except Exception:
            return False

    def _extract_user_info(self):
        try:
            result = self._get("/user/account")
            if result.get("code") != 200:
                result = self._get("/login/status")
            profile = result.get("profile", {})
            account = result.get("account", {})
            self._uid = profile.get("userId") or account.get("id", 0)
            self._nickname = profile.get("nickname", "")
        except Exception:
            pass

    def _save_cookie(self):
        COOKIE_FILE.write_text(
            json.dumps(self._clean_cookie(self.cookie), ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _show_qrcode(url: str, qrimg_b64: str = ""):
        """展示二维码。优先 ASCII 终端展示，URL 兜底。"""
        shown = False
        # 尝试终端 ASCII 二维码
        try:
            import qrcode
            import io

            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            buf = io.StringIO()
            qr.print_ascii(out=buf, invert=False)
            print(buf.getvalue(), end="")
            shown = True
        except Exception:
            pass
        # 尝试保存图片并打开
        if not shown and qrimg_b64:
            try:
                img_data = base64.b64decode(qrimg_b64)
                img_path = Path.home() / "netease_qrcode.png"
                img_path.write_bytes(img_data)
                print(f"二维码图片已保存: {img_path}")
                import os
                os.startfile(img_path)
                shown = True
            except Exception:
                pass
        # 兜底：打印 URL
        if not shown:
            print(f"二维码地址: {url}")

    # ── 搜索 ──────────────────────────────────────────────

    def search_song(self, keywords: str, limit: int = 5) -> list[dict]:
        """搜索歌曲，返回歌曲列表。405 错误自动重试。"""
        for attempt in range(3):
            try:
                result = self._get(
                    "/search",
                    {"keywords": keywords, "type": 1, "limit": limit},
                )
                if result.get("code") == 200:
                    return result.get("result", {}).get("songs", [])
            except Exception as e:
                if "405" in str(e) and attempt < 2:
                    time.sleep(1.0)
                    continue
                # 非 405 或重试用尽，静默返回空
                break
        return []

    # ── 歌单操作 ──────────────────────────────────────────

    def create_playlist(self, name: str, privacy: int = 0) -> Optional[int]:
        """
        创建歌单。privacy: 0=公开, 10=私密。
        返回 playlist_id，失败返回 None。
        """
        result = self._get(
            "/playlist/create",
            {"name": name, "privacy": str(privacy)},
        )
        if result.get("code") == 200:
            pid = result.get("id", 0)
            print(f"歌单创建成功，ID: {pid}")
            return pid
        print(f"创建歌单失败: {result}")
        return None

    def add_tracks(self, playlist_id: int, track_ids: list[int]) -> int:
        """
        向歌单批量添加歌曲。若因手机未绑定失败，提示改用手机号登录。
        """
        tracks_str = ",".join(str(tid) for tid in track_ids)
        result = self._get(
            "/playlist/tracks",
            {"op": "add", "pid": str(playlist_id), "tracks": tracks_str},
        )
        code = result.get("code") or result.get("body", {}).get("code")
        count = result.get("count") or result.get("body", {}).get("count", 0)
        if code == 200:
            return count or len(track_ids)
        msg = result.get("message") or result.get("body", {}).get("message", "")
        if "手机" in str(msg) or "绑定" in str(msg):
            print("添加歌曲失败: 需要手机号登录才能操作歌单")
            print("请用 --relogin 重新运行，选择 [1] 手机号登录")
        else:
            print(f"添加歌曲失败: {msg or result}")
        return 0

    def get_playlist_link(self, playlist_id: int) -> str:
        return f"https://music.163.com/playlist?id={playlist_id}"
