# audience: internal
# server
# 管理 NeteaseCloudMusicApi Node.js 子进程生命周期。

import subprocess
import sys
import time
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).parent
DEFAULT_PORT = 3000


class ApiServer:
    """管理 NeteaseCloudMusicApi 子进程。"""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.process: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.port}"

    @staticmethod
    def _find_node() -> str | None:
        """查找 Node.js 可执行文件。"""
        import shutil

        node = shutil.which("node")
        return node

    def start(self) -> bool:
        """启动 API 服务，等待就绪。"""
        node = self._find_node()
        if not node:
            print("错误: 未检测到 Node.js，请先安装 https://nodejs.org")
            print("安装后重新运行即可")
            return False

        # 检查依赖是否已安装
        node_modules = PROJECT_DIR / "node_modules" / "NeteaseCloudMusicApi"
        if not node_modules.exists():
            print("首次运行，正在安装 Node.js 依赖...")
            result = subprocess.run(
                ["npm", "install"],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"npm install 失败:\n{result.stderr}")
                return False

        # 使用 server_starter.js，跳过 anonymous_token 注册避免设备过多
        app_path = PROJECT_DIR / "server_starter.js"

        # 启动子进程
        env = {"PORT": str(self.port), **dict(iter(subprocess.os.environ.items()))}
        self.process = subprocess.Popen(
            [node, str(app_path)],
            cwd=PROJECT_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 等待服务就绪
        print(f"启动 API 服务 (localhost:{self.port})...")
        for _ in range(30):
            time.sleep(0.5)
            if self._health_check():
                print("API 服务就绪")
                return True
            if self.process.poll() is not None:
                print("错误: API 服务进程异常退出")
                return False

        print("错误: API 服务启动超时")
        self.stop()
        return False

    def stop(self):
        """停止 API 服务。"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _health_check(self) -> bool:
        """检查 API 服务是否就绪。"""
        try:
            resp = requests.get(
                f"{self.base_url}/search",
                params={"keywords": "test", "limit": 1},
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def __enter__(self):
        if not self.start():
            sys.exit(1)
        return self

    def __exit__(self, *args):
        self.stop()
