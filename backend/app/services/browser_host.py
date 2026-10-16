"""Isolated headed Chrome sessions with a browser-only VNC viewer."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn


def _get_profile_root() -> Path:
    env_root = os.environ.get("BROWSER_PROFILE_ROOT")
    if env_root:
        root = Path(env_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except (PermissionError, OSError):
            pass
    default_root = Path("/data/profiles")
    try:
        default_root.mkdir(parents=True, exist_ok=True)
        return default_root
    except (PermissionError, OSError):
        fallback = Path.cwd() / "tmp" / "claude_browser_profiles"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return fallback


PROFILE_ROOT = _get_profile_root()
MANAGEMENT_TOKEN = os.environ.get("BROWSER_SERVICE_TOKEN", "")
VIEWER_SECRET = os.environ.get("BROWSER_VIEWER_SECRET", "")
NOVNC_ROOT = Path(os.environ.get("NOVNC_ROOT", "/usr/share/novnc"))
PROFILE_KEY_PATTERN = re.compile(r"^[a-f0-9]{64}$")
CDP_PORT_START = int(os.environ.get("BROWSER_CDP_PORT_START", "12000"))
CDP_PORT_COUNT = int(os.environ.get("BROWSER_CDP_PORT_COUNT", "200"))
MAX_BROWSER_SESSIONS = int(os.environ.get("MAX_BROWSER_SESSIONS", "20"))


@dataclass
class BrowserSession:
    display: int
    cdp_port: int
    vnc_port: int
    processes: list[subprocess.Popen]


class SessionStart(BaseModel):
    start_url: str = "https://claude.ai/new"


class BrowserSessionHost:
    def __init__(self) -> None:
        self.sessions: dict[str, BrowserSession] = {}
        self.lock = threading.RLock()
        try:
            PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            try:
                self.chrome_executable = playwright.chromium.executable_path
            except Exception:
                self.chrome_executable = "google-chrome"

    @staticmethod
    def _key(profile_key: str) -> str:
        if not PROFILE_KEY_PATTERN.fullmatch(profile_key):
            raise HTTPException(status_code=400, detail="Invalid browser profile key.")
        return profile_key

    @staticmethod
    def _clean_stale_locks(profile_dir: Path) -> None:
        """Remove leftover lock files that prevent Chromium from launching on container restarts."""
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock_path = profile_dir / lock_name
            try:
                if lock_path.is_symlink() or lock_path.exists():
                    lock_path.unlink()
            except Exception:
                pass

    @staticmethod
    def _cdp_is_ready(port: int) -> bool:
        for host in ("127.0.0.1", "localhost"):
            try:
                req = urllib.request.Request(
                    f"http://{host}:{port}/json/version",
                    headers={"User-Agent": "Uniflow-HealthCheck"},
                )
                with urllib.request.urlopen(req, timeout=1.0) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
                    if data.get("webSocketDebuggerUrl"):
                        return True
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return False

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def _stop(self, session: BrowserSession) -> None:
        for process in reversed(session.processes):
            self._terminate(process)

    @staticmethod
    def _start_process(command: list[str], display: int, log_file=None, **kwargs) -> subprocess.Popen:
        environment = os.environ.copy()
        environment["DISPLAY"] = f":{display}"
        stdout = log_file if log_file is not None else subprocess.DEVNULL
        stderr = log_file if log_file is not None else subprocess.DEVNULL
        return subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            **kwargs,
        )

    def _reserve_ports(self, key: str) -> tuple[int, int]:
        used_ports = {session.cdp_port for session in self.sessions.values()}
        start = int(key[:8], 16) % CDP_PORT_COUNT
        for offset in range(CDP_PORT_COUNT):
            cdp_port = CDP_PORT_START + (start + offset) % CDP_PORT_COUNT
            if cdp_port in used_ports:
                continue
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", cdp_port)) != 0:
                    return cdp_port, cdp_port + 10000
        raise HTTPException(status_code=503, detail="No free browser debugging ports are available.")

    def start(self, profile_key: str, start_url: str) -> dict:
        key = self._key(profile_key)
        if not re.match(r"^https://(claude\.ai|accounts\.google\.com)(?:/|$)", start_url):
            raise HTTPException(status_code=400, detail="Browser sign-in is restricted to Claude and Google.")

        with self.lock:
            active = self.sessions.get(key)
            if active and self._cdp_is_ready(active.cdp_port):
                return {"cdp_port": active.cdp_port, "active": True}
            if active:
                self._stop(active)
                self.sessions.pop(key, None)
            if len(self.sessions) >= MAX_BROWSER_SESSIONS:
                raise HTTPException(status_code=503, detail="The hosted browser is at its session capacity.")

            display = next(
                (number for number in range(100, 3000)
                 if all(session.display != number for session in self.sessions.values())
                 and not Path(f"/tmp/.X{number}-lock").exists()),
                None,
            )
            if display is None:
                raise HTTPException(status_code=503, detail="No free virtual displays are available.")

            cdp_port, vnc_port = self._reserve_ports(key)
            profile_dir = PROFILE_ROOT / key
            try:
                profile_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            self._clean_stale_locks(profile_dir)

            processes: list[subprocess.Popen] = []
            chrome_log_handle = None
            chrome_log_path = Path(f"/tmp/chrome_session_{display}.log")

            try:
                # 1. Start Xvfb display server if available; otherwise run Chrome headless
                xvfb_path = shutil.which("Xvfb")
                headless_mode = xvfb_path is None
                if not headless_mode:
                    processes.append(self._start_process(
                        ["Xvfb", f":{display}", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                        display,
                    ))

                # Wait up to 3 seconds for Xvfb socket to appear
                x11_socket = Path(f"/tmp/.X11-unix/X{display}")
                wait_x11_deadline = time.monotonic() + 3.0
                while time.monotonic() < wait_x11_deadline:
                    if x11_socket.exists():
                        break
                    time.sleep(0.05)

                # 2. Window manager & VNC server
                if not headless_mode:
                    processes.append(self._start_process(["fluxbox"], display))
                    processes.append(self._start_process(
                        ["x11vnc", "-display", f":{display}", "-rfbport", str(vnc_port),
                         "-localhost", "-forever", "-shared", "-nopw", "-quiet",
                         "-wait", "20", "-defer", "20", "-noxdamage", "-ncache", "10", "-cursor", "arrow"],
                        display,
                    ))

                # 3. Start Chromium with container-safe defaults and logging
                try:
                    chrome_log_handle = open(chrome_log_path, "w", encoding="utf-8", errors="replace")
                except Exception:
                    chrome_log_handle = None

                chrome_cmd = [
                    self.chrome_executable,
                    f"--user-data-dir={profile_dir}",
                    f"--remote-debugging-port={cdp_port}",
                    "--remote-debugging-address=0.0.0.0",
                    "--remote-allow-origins=*",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--use-gl=swiftshader",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-breakpad",
                    "--disable-component-update",
                    "--disable-sync",
                    "--disable-default-apps",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--window-size=1280,800",
                    "--password-store=basic",
                    "--use-mock-keychain",
                    "--start-maximized",
                    start_url,
                ]
                if headless_mode:
                    chrome_cmd.insert(0, "--headless")

                processes.append(self._start_process(
                    chrome_cmd,
                    display,
                    log_file=chrome_log_handle,
                ))

                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if any(process.poll() is not None for process in processes):
                        exit_details = []
                        if chrome_log_path.exists():
                            try:
                                exit_details = chrome_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
                            except Exception:
                                pass
                        err_tail = ("\nDetails: " + " | ".join(exit_details)) if exit_details else ""
                        raise RuntimeError(f"A browser session process exited during startup.{err_tail}")
                    if self._cdp_is_ready(cdp_port):
                        session = BrowserSession(display, cdp_port, vnc_port, processes)
                        self.sessions[key] = session
                        return {"cdp_port": cdp_port, "active": True}
                    time.sleep(0.25)

                timeout_details = []
                if chrome_log_path.exists():
                    try:
                        timeout_details = chrome_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
                    except Exception:
                        pass
                err_tail = ("\nLog output: " + " | ".join(timeout_details)) if timeout_details else ""
                raise TimeoutError(f"Chrome's remote debugging endpoint did not become ready.{err_tail}")
            except Exception as error:
                if chrome_log_handle and not chrome_log_handle.closed:
                    try:
                        chrome_log_handle.close()
                    except Exception:
                        pass
                for process in reversed(processes):
                    self._terminate(process)
                self._clean_stale_locks(profile_dir)
                if isinstance(error, HTTPException):
                    raise
                raise HTTPException(status_code=503, detail=f"Could not start the isolated Chrome profile: {error}") from error

    def status(self, profile_key: str) -> dict:
        key = self._key(profile_key)
        with self.lock:
            session = self.sessions.get(key)
            active = bool(session and self._cdp_is_ready(session.cdp_port))
            return {
                "active": active,
                "cdp_port": session.cdp_port if active and session else None,
                "profile_exists": (PROFILE_ROOT / key).is_dir(),
            }

    def stop(self, profile_key: str, delete_profile: bool = False) -> None:
        key = self._key(profile_key)
        with self.lock:
            session = self.sessions.pop(key, None)
            if session:
                self._stop(session)
            profile_dir = PROFILE_ROOT / key
            self._clean_stale_locks(profile_dir)
            if delete_profile and profile_dir.exists():
                shutil.rmtree(profile_dir)


host = BrowserSessionHost()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
if not NOVNC_ROOT.exists():
    try:
        NOVNC_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
if NOVNC_ROOT.is_dir():
    app.mount("/novnc", StaticFiles(directory=str(NOVNC_ROOT)), name="novnc")
else:
    app.mount("/novnc", StaticFiles(directory=str(NOVNC_ROOT), check_dir=False), name="novnc")


def require_management_token(authorization: Optional[str] = Header(None)) -> None:
    if not MANAGEMENT_TOKEN or not hmac.compare_digest(authorization or "", f"Bearer {MANAGEMENT_TOKEN}"):
        raise HTTPException(status_code=401, detail="Invalid browser service credentials.")


def _valid_viewer_token(profile_key: str, token: str) -> bool:
    if not VIEWER_SECRET:
        return False
    try:
        encoded_payload, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            VIEWER_SECRET.encode(),
            encoded_payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return False
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4)))
        return payload.get("profile") == profile_key and payload.get("exp", 0) >= int(time.time())
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/internal/sessions/{profile_key}")
def start_session(
    profile_key: str,
    payload: SessionStart,
    _: None = Depends(require_management_token),
) -> dict:
    return host.start(profile_key, payload.start_url)


@app.get("/internal/sessions/{profile_key}")
def session_status(
    profile_key: str,
    _: None = Depends(require_management_token),
) -> dict:
    return host.status(profile_key)


@app.delete("/internal/sessions/{profile_key}")
def stop_session(
    profile_key: str,
    delete_profile: bool = False,
    _: None = Depends(require_management_token),
) -> dict:
    host.stop(profile_key, delete_profile=delete_profile)
    return {"stopped": True, "profile_deleted": delete_profile}


@app.get("/viewer/{profile_key}", response_class=HTMLResponse)
def viewer(profile_key: str) -> str:
    key = host._key(profile_key)
    if not host.status(key)["active"]:
        raise HTTPException(status_code=409, detail="Start this user's Claude browser session first.")
    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Uniflow Claude sign-in</title>
<style>html,body,#screen{{margin:0;width:100%;height:100%;background:#151515}}#notice{{position:fixed;z-index:2;top:12px;left:12px;color:white;font:14px sans-serif}}</style>
</head><body><div id="notice">Connecting to your private Claude browser…</div><div id="screen"></div>
<script type="module">
import RFB from "/novnc/core/rfb.js";
const token = location.hash.slice(1);
if (!token) throw new Error("Viewer link is missing its short-lived access token.");
const scheme = location.protocol === "https:" ? "wss:" : "ws:";
const rfb = new RFB(document.getElementById("screen"),
  `${{scheme}}//${{location.host}}/viewer/{key}/websockify?token=${{encodeURIComponent(token)}}`);
rfb.scaleViewport = true;
rfb.resizeSession = false;
rfb.qualityLevel = 6;
rfb.compressionLevel = 2;
rfb.showDotCursor = true;
rfb.addEventListener("connect", () => document.getElementById("notice").remove());
rfb.addEventListener("disconnect", () => document.getElementById("notice").textContent = "Browser disconnected.");
</script></body></html>"""


@app.websocket("/viewer/{profile_key}/websockify")
async def viewer_websocket(websocket: WebSocket, profile_key: str, token: str) -> None:
    try:
        key = host._key(profile_key)
        if not _valid_viewer_token(key, token):
            await websocket.close(code=1008)
            return
        session = host.sessions.get(key)
        if not session or not host._cdp_is_ready(session.cdp_port):
            await websocket.close(code=1011)
            return
        reader, writer = await asyncio.open_connection("127.0.0.1", session.vnc_port)
    except (HTTPException, OSError):
        await websocket.close(code=1011)
        return

    await websocket.accept()

    async def browser_to_viewer() -> None:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            await websocket.send_bytes(data)

    async def viewer_to_browser() -> None:
        while True:
            data = await websocket.receive_bytes()
            writer.write(data)
            await writer.drain()

    tasks = [
        asyncio.create_task(browser_to_viewer()),
        asyncio.create_task(viewer_to_browser()),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    except (WebSocketDisconnect, OSError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()
        await websocket.close()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7900, access_log=False)
