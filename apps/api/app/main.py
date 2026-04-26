import os
import signal
import subprocess
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes.feedback import router as feedback_router
from app.api.routes.health import router as health_router
from app.api.routes.imports import router as imports_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.prompt_profiles import router as prompt_profiles_router
from app.api.routes.search import router as search_router
from app.api.routes.source_auth import router as source_auth_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine


def _kill_playwright_processes() -> None:
    """只杀掉当前 Python 进程的子进程树中的 Chromium/Chrome，
    不影响用户自己打开的浏览器。"""
    try:
        if sys.platform == "win32":
            # Windows: 用 taskkill /T 杀进程树（只杀当前进程的子进程）
            pid = os.getpid()
            # 先找到当前进程树中的 chrome/chromium 子进程
            result = subprocess.run(
                ["wmic", "process", "where",
                 f"ParentProcessId={pid} and (Name='chrome.exe' or Name='chromium.exe')",
                 "get", "ProcessId"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.isdigit():
                    child_pid = int(line)
                    # 用 /T 杀整个子树，/F 强制
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(child_pid)],
                        capture_output=True, timeout=5,
                    )
                    print(f"[Shutdown] 已停止 Playwright 浏览器进程 PID={child_pid}")
            
            # 也检查孙进程（Python -> node -> chromium 的情况）
            result2 = subprocess.run(
                ["wmic", "process", "where",
                 f"ParentProcessId={pid}",
                 "get", "ProcessId"],
                capture_output=True, text=True, timeout=5,
            )
            child_pids = []
            for line in result2.stdout.strip().split("\n"):
                line = line.strip()
                if line.isdigit():
                    child_pids.append(int(line))
            
            for cpid in child_pids:
                result3 = subprocess.run(
                    ["wmic", "process", "where",
                     f"ParentProcessId={cpid} and (Name='chrome.exe' or Name='chromium.exe')",
                     "get", "ProcessId"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result3.stdout.strip().split("\n"):
                    line = line.strip()
                    if line.isdigit():
                        grandchild_pid = int(line)
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(grandchild_pid)],
                            capture_output=True, timeout=5,
                        )
                        print(f"[Shutdown] 已停止 Playwright 浏览器进程 PID={grandchild_pid}")
        else:
            # Linux/macOS: pkill -P 只杀指定父进程的子进程
            pid = os.getpid()
            subprocess.run(["pkill", "-f", f"--parent={pid}", "chromium"], capture_output=True, timeout=5)
            subprocess.run(["pkill", "-f", f"--parent={pid}", "chrome"], capture_output=True, timeout=5)
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI 获客线索发现 Agent API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")
    app.include_router(imports_router, prefix="/api")
    app.include_router(feedback_router, prefix="/api")
    app.include_router(prompt_profiles_router, prefix="/api")
    app.include_router(search_router, prefix="/api")
    app.include_router(source_auth_router, prefix="/api")

    @app.on_event("startup")
    def startup() -> None:
        Base.metadata.create_all(bind=engine)

        # ★ SQLite 不支持 ALTER ADD COLUMN 的自动迁移，手动补列
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE search_job ADD COLUMN min_score INTEGER DEFAULT 0"))
                conn.commit()
            except Exception:
                pass  # 列已存在，忽略

        # ★ 注册信号处理器：Ctrl+C 时立即杀掉 Playwright 子进程
        def _signal_handler(signum, frame):
            print(f"\n[Shutdown] 收到信号 {signum}，正在停止所有爬虫进程...")
            from app.scrapers.joinf.service import cancel_all_jobs
            cancel_all_jobs()
            _kill_playwright_processes()
            # 重新抛出信号让 uvicorn 正常退出
            signal.signal(signum, signal.SIG_DFL)
            raise KeyboardInterrupt()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

    @app.on_event("shutdown")
    def shutdown() -> None:
        """服务关闭时：取消所有运行中的 job，杀掉 Playwright 子进程"""
        print("[Shutdown] 正在清理所有爬虫任务和浏览器进程...")
        from app.scrapers.joinf.service import cancel_all_jobs
        cancel_all_jobs()
        _kill_playwright_processes()

    return app


app = create_app()
