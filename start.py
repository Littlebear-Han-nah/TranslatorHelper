import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path

def main():
    """
    Python 跨平台一键启动脚本
    自动校验依赖、打包前端静态文件并启动 FastAPI 服务
    """
    root_dir = Path(__file__).resolve().parent
    os.chdir(root_dir)

    print("=" * 60)
    print("🚀 课件/论文智能双语对照翻译系统 启动器")
    print("=" * 60)

    # 检查前端打包目录
    dist_dir = root_dir / "frontend" / "dist"
    if not dist_dir.exists():
        print("📦 正在构建前端界面 (npm run build)...")
        subprocess.run(["npm", "--prefix", "frontend", "run", "build"], check=True)

    print("🌐 启动 Web 服务: http://127.0.0.1:8000")
    print("提示: 在终端按 Ctrl+C 可停止运行。")
    print("=" * 60)

    # 自动打开浏览器
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8000")

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    # 启动 Uvicorn 服务器
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=False)

if __name__ == "__main__":
    main()
