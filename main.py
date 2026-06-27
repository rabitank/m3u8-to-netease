# audience: internal
# main
# CLI 入口 — 串联解析、登录、匹配、创建歌单全流程。

import argparse
import sys
import time
from pathlib import Path

from m3u8_parser import parse_m3u8, Track
from netease_api import NeteaseAPI
from server import ApiServer
from matcher import match_song, _format_song, similarity


MAX_BATCH = 1000


def _login_interactive(api: NeteaseAPI) -> bool:
    """短信验证码登录。网易云行为验证要求必须使用验证码。"""
    print("\n登录网易云音乐...")
    phone = input("手机号: ").strip()
    if not phone:
        print("手机号不能为空")
        return False
    print("（需要短信验证码，密码或二维码方式已禁用）")
    return api.login_phone(phone, "")  # 空密码走短信验证码


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 .m3u8 播放列表转换为网易云音乐云歌单",
    )
    parser.add_argument(
        "m3u8_file",
        help=".m3u8 播放列表文件路径",
    )
    parser.add_argument(
        "--name", "-n",
        default=None,
        help="歌单名称（默认使用 .m3u8 文件名）",
    )
    parser.add_argument(
        "--privacy", "-p",
        type=int,
        choices=[0, 10],
        default=0,
        help="歌单隐私: 0=公开(默认), 10=私密",
    )
    parser.add_argument(
        "--cookie",
        default=None,
        help="直接使用 cookie 字符串登录（跳过二维码）",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="自动模式，高置信度自动采纳，低置信度汇聚到末尾手动选择",
    )
    parser.add_argument(
        "--relogin",
        action="store_true",
        help="强制重新登录（删除缓存的 cookie）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="搜索间隔秒数（默认 0.4，避免触发频率限制）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="匹配置信度阈值 0~1（默认 0.70）",
    )
    return parser.parse_args()


def _confirm_match(track: Track, song: dict, score: float) -> str:
    """交互确认一首歌曲的匹配结果。返回 'y'/'n'/'s'/'q'。"""
    print(f"\n  [{track.index + 1}] {track.display}")
    print(f"       候选: {_format_song(song)}  (置信度 {score:.0%})")
    while True:
        choice = input("       [y]接受 [n]跳过 [s]手动搜索 [q]退出: ").strip().lower()
        if choice in ("y", "n", "s", "q"):
            return choice
        print("       无效输入，请重试")


def _manual_search(api: NeteaseAPI, track: Track) -> tuple[dict | None, float]:
    """手动输入关键词搜索，返回 (song, score)。"""
    kw = input(f"       输入搜索关键词 (回车用默认 '{track.display}'): ").strip()
    if not kw:
        kw = track.display
    results = api.search_song(kw, limit=10)
    if not results:
        print("       未找到结果")
        return None, 0.0
    for j, s in enumerate(results):
        print(f"       [{j}] {_format_song(s)}  (id: {s.get('id')})")
    sel = input(f"       选择序号 [0-{len(results) - 1}], 或 n 跳过: ").strip()
    if sel.lower() == "n":
        return None, 0.0
    try:
        idx = int(sel)
        chosen = results[idx]
        score = similarity(track.display, _format_song(chosen))
        return chosen, score
    except (ValueError, IndexError):
        return None, 0.0


def main():
    # 修复 Windows 终端 GBK 编码导致的 Unicode 显示问题
    try:
        import sys as _sys
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = _parse_args()

    # ── 解析 .m3u8 ────────────────────────────────────────
    m3u8_path = Path(args.m3u8_file)
    if not m3u8_path.exists():
        print(f"错误: 文件不存在 - {m3u8_path}")
        sys.exit(1)

    print(f"解析播放列表: {m3u8_path.name}")
    tracks = parse_m3u8(str(m3u8_path))
    if not tracks:
        print("未找到任何歌曲，退出")
        sys.exit(0)
    print(f"共解析到 {len(tracks)} 首歌曲\n")

    playlist_name = args.name or m3u8_path.stem

    # ── 启动 API 服务 + 登录 ──────────────────────────────
    with ApiServer() as server:
        api = NeteaseAPI(base_url=server.base_url)

        if args.relogin:
            from netease_api import COOKIE_FILE
            COOKIE_FILE.unlink(missing_ok=True)
            print("已删除缓存 cookie，请重新登录\n")

        if args.cookie:
            if api.login_cookie(args.cookie):
                print(f"Cookie 登录成功: {api.nickname}\n")
            else:
                print("Cookie 登录失败，请检查 cookie 是否有效")
                sys.exit(1)
        elif not args.relogin and api.try_auto_login():
            print(f"自动登录成功: {api.nickname}\n")
        else:
            if not _login_interactive(api):
                print("登录失败，退出")
                sys.exit(1)
            print(f"登录成功: {api.nickname}\n")

        # ── 匹配歌曲 ──────────────────────────────────────
        matched: list[dict] = []
        unmatched: list[tuple[Track, list[dict]]] = []
        skipped = 0

        print("开始匹配歌曲...")
        print("─" * 50)

        for track in tracks:
            time.sleep(args.delay)
            results = api.search_song(track.display, limit=5)
            match = match_song(track.artist, track.title, results, args.threshold)

            if match is not None:
                song, score = match
                if args.auto:
                    print(f"  [{track.index + 1:>3}/{len(tracks)}] {track.display}")
                    print(f"         → {_format_song(song)}  ({score:.0%})")
                    matched.append(song)
                else:
                    choice = _confirm_match(track, song, score)
                    if choice == "y":
                        matched.append(song)
                    elif choice == "n":
                        skipped += 1
                    elif choice == "s":
                        ms, ms_score = _manual_search(api, track)
                        if ms is not None:
                            matched.append(ms)
                        else:
                            skipped += 1
                    elif choice == "q":
                        print("用户取消操作")
                        sys.exit(0)
            else:
                if args.auto:
                    print(f"  [{track.index + 1:>3}/{len(tracks)}] {track.display}  ❌ 无匹配")
                    unmatched.append((track, results))
                else:
                    print(f"\n  [{track.index + 1}] {track.display}")
                    print(f"        未找到匹配 (最高低于阈值 {args.threshold:.0%})")
                    choice = input("        [s]手动搜索 [n]跳过 [q]退出: ").strip().lower()
                    if choice == "s":
                        ms, ms_score = _manual_search(api, track)
                        if ms is not None:
                            matched.append(ms)
                        else:
                            skipped += 1
                    elif choice == "q":
                        print("用户取消操作")
                        sys.exit(0)
                    else:
                        skipped += 1

        # ── 自动模式：手动处理未匹配歌曲 ──────────────────
        if args.auto and unmatched:
            print(f"\n以下 {len(unmatched)} 首未能自动匹配，请手动选择：")
            for track, results in unmatched:
                print(f"\n  ─────────────────────")
                print(f"  [{track.index + 1}/{len(tracks)}] {track.display}")
                if results:
                    for j, s in enumerate(results):
                        print(f"    [{j}] {_format_song(s)}  (id: {s.get('id')})")
                else:
                    print("    无搜索结果")
                n_results = len(results)
                prompt = f"    选择 [0-{n_results - 1}]" if n_results else "    "
                prompt += " / [s]自定义搜索 / [n]跳过 / [q]结束处理: "
                while True:
                    choice = input(prompt).strip().lower()
                    if choice == "q":
                        print("    结束手动处理")
                        break
                    elif choice == "n":
                        skipped += 1
                        break
                    elif choice == "s":
                        ms, _ = _manual_search(api, track)
                        if ms is not None:
                            matched.append(ms)
                            print(f"    ✓ 已添加: {_format_song(ms)}")
                        else:
                            skipped += 1
                        break
                    else:
                        try:
                            idx = int(choice)
                            if 0 <= idx < n_results:
                                chosen = results[idx]
                                matched.append(chosen)
                                print(f"    ✓ 已添加: {_format_song(chosen)}")
                                break
                        except (ValueError, IndexError):
                            pass
                        print("    无效选择，请重试")
                if choice == "q":
                    break

        # ── 汇总 ──────────────────────────────────────────
        print("\n" + "=" * 50)
        print(f"匹配结果: {len(matched)}/{len(tracks)} 首确认, {skipped} 首跳过")
        print(f"歌单名称: {playlist_name}")
        print(f"隐私设置: {'私密' if args.privacy == 10 else '公开'}")
        print("=" * 50)

        if not matched:
            print("没有匹配到任何歌曲，退出")
            sys.exit(0)

        if not args.auto:
            confirm = input("\n确认创建歌单? [Y/n]: ").strip().lower()
            if confirm and confirm != "y":
                print("已取消")
                sys.exit(0)

        # ── 创建歌单 ──────────────────────────────────────
        print("\n正在创建歌单...")
        pid = api.create_playlist(playlist_name, args.privacy)
        if pid is None:
            print("歌单创建失败")
            sys.exit(1)

        # ── 分批添加歌曲 ──────────────────────────────────
        track_ids = [s["id"] for s in matched]
        total_added = 0
        for i in range(0, len(track_ids), MAX_BATCH):
            batch = track_ids[i : i + MAX_BATCH]
            count = api.add_tracks(pid, batch)
            total_added += count
            print(f"  已添加 [{i + 1}-{i + len(batch)}] {count} 首")

        print(f"\n完成! 共添加 {total_added} 首歌曲")
        print(f"歌单链接: {api.get_playlist_link(pid)}")


if __name__ == "__main__":
    main()
