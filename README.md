# m3u8-to-netease

将 `.m3u8` 播放列表转换为网易云音乐云歌单的命令行工具。

## 典型场景

- **Windows Media Player 歌单迁移**：微软自带播放器使用 `.m3u8` 保存播放列表，右键歌单 → "打开文件位置" 即可找到。用本工具一键导入网易云，不再受本地文件路径限制
- **本地音乐库上云**：整理多年的本地 MP3/FLAC 播放列表，导入网易云后随时随地收听
- **跨平台歌单转移**：任何支持导出 `.m3u8` 的播放器（Foobar2000、VLC、AIMP 等）均可通过本工具转移到网易云

## 原理

```
.m3u8 → 解析歌曲信息 → 网易云API搜索匹配 → 创建云歌单 → 批量添加歌曲
```

通过本地 [NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi) 服务对接网易云，自动处理加密与登录，无需手动操作。

## 安装

```bash
# 要求：Python 3.10+、Node.js 18+
git clone https://github.com/rabitank/m3u8-to-netease.git
cd m3u8-to-netease
pip install -r requirements.txt
```

首次运行会自动执行 `npm install` 安装 Node.js 依赖。

## 使用

```bash
# 基本用法
python main.py playlist.m3u8

# 自动模式（高置信度自动采纳，低置信度末尾手动选择）
python main.py playlist.m3u8 --auto

# 指定歌单名和隐私设置
python main.py playlist.m3u8 --name "我的收藏" --privacy 10

# 强制重新登录
python main.py playlist.m3u8 --relogin
```

### 登录

仅支持**短信验证码登录**（网易云行为验证要求）：

```
登录网易云音乐...
手机号: 138xxxxxxxx
（需要短信验证码，密码或二维码方式已禁用）
验证码已发送，请查收短信
输入短信验证码: xxxx
登录成功: 昵称
```

登录成功后 cookie 保存在 `~/.m3u8-to-netease-cookie.json`，下次启动自动复用。

### 命令行参数

| 参数 | 说明 |
|------|------|
| `m3u8_file` | .m3u8 播放列表文件路径（必填） |
| `--name, -n` | 歌单名称（默认使用文件名） |
| `--privacy, -p` | 隐私设置：`0` 公开，`10` 私密（默认 0） |
| `--auto` | 自动模式，高置信度自动采纳，低置信度末尾集中处理 |
| `--relogin` | 强制重新登录（删除缓存 cookie） |
| `--delay` | 搜索间隔秒数（默认 0.4，避免限流） |
| `--threshold` | 匹配置信度阈值 0~1（默认 0.70） |

### 匹配模式

- **交互模式**（默认）：逐首确认，每首可选 `[y]接受 [n]跳过 [s]自定义搜索`
- **自动模式**（`--auto`）：高置信度自动采纳，低置信度歌曲汇聚到末尾，列出所有候选供手动选择

## 支持的 .m3u8 格式

Windows Media Player、Foobar2000、VLC、AIMP 等播放器导出的 `.m3u8` 均可识别：

```
#EXTM3U
#EXTINF:263,周杰伦 - 晴天
D:\Music\周杰伦 - 晴天.mp3
#EXTINF:249,林俊杰 - 江南
D:\Music\林俊杰 - 江南.flac
```

支持 `#EXTINF` 标签及直接文件路径行，自动从 `歌手 - 歌名` 格式解析元信息。

## 技术栈

Python + NeteaseCloudMusicApi (Node.js)，Python 通过子进程启动 Node API 服务，所有加密与风控交由社区维护的 API 处理。
