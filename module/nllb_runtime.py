"""로컬 NLLB 설치·기동·주소 설정을 관리한다."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests

APP_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = APP_ROOT / "nllb_config.json"
LOG_FILE = APP_ROOT / "nllb_server.log"
PID_FILE = APP_ROOT / "nllb_server.pid"
SERVER_SCRIPT = Path(__file__).resolve().parent / "nllb_server.py"
DEFAULT_ENDPOINT = "http://127.0.0.1:8000/translate"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
REQUIRED_MODULES = {
    "ctranslate2": "ctranslate2",
    "transformers": "transformers",
    "sentencepiece": "sentencepiece",
}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def normalize_endpoint(value: str | None) -> str:
    """사용자 입력을 항상 /translate 엔드포인트 URL로 정규화한다."""
    endpoint = (value or "").strip() or load_endpoint_setting() or DEFAULT_ENDPOINT
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"http://{endpoint}"
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("NLLB 주소는 http:// 또는 https://로 시작해야 합니다.")
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        path = "/translate"
    elif not path.rsplit("/", 1)[-1].lower().startswith("translate"):
        path = f"{path}/translate"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def load_endpoint_setting() -> str:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data.get("endpoint_url", "") if isinstance(data, dict) else ""
    except (OSError, json.JSONDecodeError):
        return ""


def save_endpoint_setting(endpoint: str) -> str:
    endpoint = normalize_endpoint(endpoint)
    temp = CONFIG_FILE.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps({"endpoint_url": endpoint}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, CONFIG_FILE)
    return endpoint


def endpoint_is_local(endpoint: str) -> bool:
    hostname = (urlparse(endpoint).hostname or "").lower()
    return hostname in LOCAL_HOSTS


def health_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    return urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))


def check_endpoint(endpoint: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        response = requests.get(health_url(endpoint), timeout=timeout)
        if response.status_code < 500:
            return True, f"HTTP {response.status_code}"
        return False, f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)


def missing_packages() -> list[str]:
    return [package for module, package in REQUIRED_MODULES.items() if importlib.util.find_spec(module) is None]


def install_missing_packages(log_func=print) -> None:
    """누락된 선택형 NLLB 런타임만 현재 인터프리터에 설치한다."""
    packages = missing_packages()
    if not packages:
        return
    log = log_func or print
    packages = list(dict.fromkeys(packages + ["fastapi", "uvicorn"]))
    log(
        "⬇️ 로컬 NLLB 구성 요소가 없어 현재 Python 환경에 자동 설치합니다: "
        + ", ".join(packages)
    )
    log("⏳ 첫 설치는 Torch/Transformers와 번역 모델 때문에 시간이 오래 걸릴 수 있습니다.")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *packages],
            cwd=str(APP_ROOT),
            text=True,
            capture_output=True,
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("NLLB 자동 설치가 30분을 초과했습니다.") from exc
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "알 수 없는 pip 오류")[-3000:]
        raise RuntimeError(f"NLLB 자동 설치 실패:\n{tail}")
    still_missing = missing_packages()
    if still_missing:
        raise RuntimeError("설치 후에도 NLLB 구성 요소가 없습니다: " + ", ".join(still_missing))
    log("✅ 로컬 NLLB 런타임 설치 완료")


def _read_running_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    if os.name == "nt":
        return pid
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


def _port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def start_local_server(endpoint: str, log_func=print) -> subprocess.Popen:
    log = log_func or print
    parsed = urlparse(endpoint)
    host = parsed.hostname or DEFAULT_HOST
    if host == "0.0.0.0":
        host = DEFAULT_HOST
    port = parsed.port or DEFAULT_PORT
    if not _port_available(host, port):
        raise RuntimeError(f"NLLB 포트 {host}:{port}가 다른 프로그램에서 사용 중입니다.")

    install_missing_packages(log)
    log_file = open(LOG_FILE, "a", encoding="utf-8")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT), "--host", host, "--port", str(port)],
        cwd=str(APP_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        **kwargs,
    )
    PID_FILE.write_text(str(process.pid), encoding="ascii")
    log(f"🚀 로컬 NLLB 서버를 시작했습니다: {endpoint} (PID {process.pid})")
    log(f"📄 서버 로그: {LOG_FILE}")
    return process


def wait_until_ready(
    endpoint: str,
    process: subprocess.Popen | None = None,
    timeout: float = 3600,
    cancel_event=None,
    log_func=print,
) -> None:
    log = log_func or print
    deadline = time.monotonic() + timeout
    logged_wait = False
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            raise InterruptedError("NLLB 준비 대기 중 번역이 중지되었습니다.")
        ready, detail = check_endpoint(endpoint, timeout=1.5)
        if ready:
            log(f"✅ NLLB 서버 연결 완료: {endpoint} ({detail})")
            return
        if process is not None and process.poll() is not None:
            tail = ""
            try:
                tail = LOG_FILE.read_text(encoding="utf-8", errors="ignore")[-2500:]
            except OSError:
                pass
            raise RuntimeError(f"NLLB 서버가 종료되었습니다 (code={process.returncode}).\n{tail}")
        if not logged_wait:
            log("⏳ NLLB 모델 다운로드/로딩 중입니다. 첫 실행은 시간이 오래 걸릴 수 있습니다...")
            logged_wait = True
        time.sleep(1)
    raise RuntimeError(
        f"NLLB 서버 준비 시간이 1시간을 초과했습니다. '{LOG_FILE}'에서 모델 다운로드 상태를 확인하세요."
    )


def ensure_nllb_endpoint(
    endpoint: str | None = None,
    auto_install: bool = True,
    auto_start: bool = True,
    cancel_event=None,
    log_func=print,
) -> str:
    """사용자 주소 또는 로컬 기본 주소가 준비될 때까지 보장한다."""
    endpoint = normalize_endpoint(endpoint)
    save_endpoint_setting(endpoint)
    ready, detail = check_endpoint(endpoint)
    if ready:
        (log_func or print)(f"✅ 기존 NLLB 서버를 사용합니다: {endpoint} ({detail})")
        return endpoint

    if not endpoint_is_local(endpoint):
        raise RuntimeError(
            f"사용자 지정 NLLB 서버에 연결할 수 없습니다: {endpoint} ({detail}). "
            "GUI의 NLLB 주소가 올바른지 확인하세요."
        )
    if not auto_start:
        raise RuntimeError(f"로컬 NLLB 서버가 실행 중이지 않습니다: {endpoint}")

    log = log_func or print
    process = None
    if auto_install:
        install_missing_packages(log)
    process = start_local_server(endpoint, log)
    wait_until_ready(endpoint, process, cancel_event=cancel_event, log_func=log)
    return endpoint