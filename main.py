import base64
import json
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 기존 모듈 및 설정 변수 로드
from cli_translator import (
    load_or_setup_launcher_paths,
    find_modpacks_deep,
    parse_target_localization_files,
    get_final_lang_code,
    CONFIG_FILE
)
SESSION_FILE = Path(__file__).resolve().parent / 'translation_session.json'

try:
    from module import (
        extract_strings_from_file,
        save_translated_file,
        encode_text,
        decode_text,
        get_translator,
        build_batches,
        translate_batch,
        scan_and_build_local_glossary
    )
    from module.translator_core import ENV_FILE
    from module.nllb_runtime import DEFAULT_ENDPOINT as DEFAULT_NLLB_ENDPOINT
    from module.nllb_runtime import load_endpoint_setting as load_nllb_endpoint
except ImportError as e:
    print(f"❌ [오류] 'module' 패키지를 로드할 수 없습니다: {e}")
    sys.exit(1)

app = FastAPI(title="Minecraft Translation Backend Server")

# 크롬 브라우저(프론트엔드 HTML)에서 들어오는 요청을 허용하기 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 글로벌 상태 관리 객체 (실시간 로그 및 진행률 전송용)
STATUS_INFO = {
    "text": "대기 중...", "pct": 0, "logs": [], "complete": False,
    "stopped": False, "zip_filename": "", "b64_data": "",
    "started_at": 0, "elapsed_seconds": 0, "eta_seconds": None,
    "processed_chunks": 0, "total_chunks": 0,
    "scan_phase": "idle", "scan_processed": 0, "scan_total": 0,
    "scan_percent": 0, "scan_eta_seconds": None,
}
STATUS_LOCK = threading.Lock()
MODPACKS_CACHE = []
CANCEL_EVENT = threading.Event()


class TranslationRequest(BaseModel):
    src_lang: str
    dest_lang: str
    skip_chapters: bool
    engine_choice: str
    selected_pack_idx: int
    pack_path: str = ""
    selected_file_paths: list[str] = Field(default_factory=list)
    selected_mods: list[str] = Field(default_factory=list)
    api_key: str
    model_name: str
    endpoint_url: str


class SessionResponse(BaseModel):
    exists: bool
    session: dict | None = None


def save_session(req: TranslationRequest) -> None:
    request = req.model_dump()
    if not request.get("pack_path") and 0 <= req.selected_pack_idx < len(MODPACKS_CACHE):
        request["pack_path"] = MODPACKS_CACHE[req.selected_pack_idx]["root_path"]
    session = {"request": request, "saved_at": datetime.now().isoformat(), "status": STATUS_INFO.get("text", "")}
    temp = SESSION_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, SESSION_FILE)


def load_session() -> dict | None:
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("request"), dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def add_log(msg: str):
    print(msg)
    with STATUS_LOCK:
        STATUS_INFO["logs"].append(msg)


def set_status(text: str, pct: int):
    with STATUS_LOCK:
        STATUS_INFO["text"] = text
        STATUS_INFO["pct"] = pct


def update_timing_status():
    now = time.time()
    with STATUS_LOCK:
        started = STATUS_INFO["started_at"]
        processed = STATUS_INFO["processed_chunks"]
        total = STATUS_INFO["total_chunks"]
        elapsed = now - started if started else 0
        STATUS_INFO["elapsed_seconds"] = round(elapsed)
        if processed > 0 and total >= processed:
            eta = (elapsed / processed) * (total - processed)
            STATUS_INFO["eta_seconds"] = round(eta)

def is_cancelled():
    return CANCEL_EVENT.is_set()


LAST_HEARTBEAT_TIME = time.time()
BROWSER_CLOSE_SIGNALED = False
BROWSER_CLOSE_TIME = 0
# 브라우저에서 명시적 닫힘 신호를 보낸 뒤, 새로고침/탭 전환 복귀를 기다리는 유예 시간
BROWSER_SHUTDOWN_GRACE_SECONDS = 20
# 하트비트가 이 시간 이상 끊기면 안전망으로 종료 (백그라운드 탭 지연/일시적 네트워크 끊김/시스템 슬립 대비)
HEARTBEAT_TIMEOUT_SECONDS = 300


@app.post("/api/heartbeat")
def receive_heartbeat():
    """프론트엔드로부터 생존 신호를 받습니다."""
    global LAST_HEARTBEAT_TIME, BROWSER_CLOSE_SIGNALED
    LAST_HEARTBEAT_TIME = time.time()
    # 하트비트가 다시 도착하면 브라우저가 살아있다는 뜻이므로 종료 신호를 취소한다.
    # (새로고침/탭 전환 시 pagehide 이벤트 후 재로드되면 즉시 하트비트가 재개됨)
    BROWSER_CLOSE_SIGNALED = False
    return {"status": "alive"}


@app.post("/api/browser-close")
def receive_browser_close():
    """브라우저가 닫힘을 알립니다. 새로고침·탭 전환 시에도 발생할 수 있으므로 서버는 유예 후 종료합니다."""
    global BROWSER_CLOSE_SIGNALED, BROWSER_CLOSE_TIME
    BROWSER_CLOSE_SIGNALED = True
    BROWSER_CLOSE_TIME = time.time()
    return {"status": "ok"}


def _monitor_browser_closed():
    """브라우저가 닫혔는지 감지하여 서버를 자동 종료합니다."""
    global LAST_HEARTBEAT_TIME, BROWSER_CLOSE_SIGNALED
    while True:
        time.sleep(2)  # 2초마다 체크

        # 1) 브라우저가 명시적으로 닫힘 신호를 보낸 경우
        #    - 유예 시간 내에 하트비트가 다시 오면 (새로고침/탭 복귀) 신호가 취소된다.
        #    - 유예 시간이 지나도 하트비트가 없으면 실제로 닫힌 것으로 간주하고 종료한다.
        if BROWSER_CLOSE_SIGNALED:
            if time.time() - BROWSER_CLOSE_TIME > BROWSER_SHUTDOWN_GRACE_SECONDS:
                print("🔌 브라우저 탭 닫힘 신호 확인. API 서버를 종료합니다.")
                os._exit(0)
            continue

        # 2) 안전망: 하트비트가 매우 오랜 시간 중단된 경우 (브라우저 크래시 등)
        #    - 5분(300초)으로 완화하여 백그라운드 탭 타이머 지연, 일시적 네트워크 끊김,
        #      시스템 슬립 등으로 인한 오판을 방지한다.
        if time.time() - LAST_HEARTBEAT_TIME > HEARTBEAT_TIMEOUT_SECONDS:
            print("🔌 하트비트가 5분 이상 수신되지 않아 API 서버를 종료합니다.")
            os._exit(0)

@app.get("/api/initial-data")
def get_initial_data():
    """초기 세팅 값 및 검색된 모드팩 리스트를 반환합니다 (Prism / CurseForge 완벽 분기)."""
    global MODPACKS_CACHE
    config_data = load_or_setup_launcher_paths()
    try:
        MODPACKS_CACHE = find_modpacks_deep(config_data)
    except Exception:
        MODPACKS_CACHE = []

    formatted_packs = []
    for idx, pack in enumerate(MODPACKS_CACHE):
        version = "1.0.0"
        # 기본 아이콘 (Dicebear 식별자)
        icon_src = f"https://api.dicebear.com/7.x/identicon/svg?seed={pack['name']}"

        launcher_type = pack["launcher"].lower()
        root_path = pack['root_path']

        # 1. Prism Launcher 대응 로직
        if "prism" in launcher_type:
            # 📌 버전 추출: instance.cfg 내 ManagedPackVersionName 파싱
            cfg_path = os.path.join(root_path, "..\instance.cfg")
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.startswith("ManagedPackVersionName="):
                                version = line.split("=", 1)[1].strip()
                                break
                except Exception:
                    pass

            # 📌 아이콘 추출: minecraft/icon.png 가 있으면 Base64 변환하여 프론트 전송
            icon_path = os.path.join(root_path, "icon.png")
            if os.path.exists(icon_path):
                try:
                    with open(icon_path, "rb") as img_f:
                        b64_img = base64.b64encode(img_f.read()).decode("utf-8")
                        icon_src = f"data:image/png;base64,{b64_img}"
                except Exception:
                    pass

        # 2. CurseForge Launcher 대응 로직
        else:
            manifest_path = os.path.join(root_path, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                        # manifest.json의 version 필드
                        version = m_data.get("version", "1.0.0")

                        # 📌 아이콘 추출: manifest.json 내 image 주소 파싱 (기본 필드 확인)
                        if "image" in m_data and m_data["image"]:
                            icon_src = m_data["image"]
                except Exception:
                    pass

        formatted_packs.append({
            "index": idx,
            "launcher": pack["launcher"],
            "name": pack["name"],
            "version": version,
            "icon": icon_src,
            "root_path": root_path,
            "config_path": pack["config_path"]
        })

    saved_endpoint = (config_data.get("saved_endpoint_url") or "").strip()
    legacy_endpoint = "http://192.168.0.35:8000/translate"
    if not saved_endpoint or saved_endpoint == legacy_endpoint:
        saved_endpoint = load_nllb_endpoint() or DEFAULT_NLLB_ENDPOINT

    return {
        "config": {
            "saved_engine_choice": config_data.get("saved_engine_choice", "1"),
            "saved_api_key": config_data.get("saved_api_key", ""),
            "saved_model_name": config_data.get("saved_model_name", ""),
            "saved_endpoint_url": saved_endpoint,
        },
        "modpacks": formatted_packs
    }


@app.get("/api/translation-files")
def get_translation_files(root_path: str, src_lang: str = "en", dest_lang: str = "ko"):
    root_path = os.path.abspath(root_path)
    if not os.path.isdir(root_path):
        raise ValueError("모드팩 경로가 존재하지 않습니다.")
    tasks = parse_target_localization_files(os.path.join(root_path, "config"), root_path, src_lang, get_final_lang_code(dest_lang))
    return {"files": [{"path": t["input_path"], "relative_path": os.path.relpath(t["input_path"], root_path), "name": t["display_name"], "kind": "quest" if t["is_quest"] else "mod"} for t in tasks]}


@app.get("/api/session", response_model=SessionResponse)
def get_session():
    session = load_session()
    return SessionResponse(exists=bool(session), session=session)


@app.post("/api/session/save")
def save_translation_session(req: TranslationRequest):
    save_session(req)
    add_log("💾 번역 세션이 저장되었습니다. 완료된 번역은 캐시로 보존됩니다.")
    return {"status": "saved"}


@app.post("/api/session/load", response_model=SessionResponse)
def load_translation_session():
    session = load_session()
    if not session:
        raise ValueError("저장된 번역 세션이 없습니다.")
    return SessionResponse(exists=True, session=session)


@app.post("/api/stop-translation")
def stop_translation():
    if not STATUS_INFO["complete"]:
        CANCEL_EVENT.set()
        add_log("⏹ 사용자가 번역 작업을 중지했습니다.")
        set_status("⏹ 중지 요청됨 - 현재 작업 종료 대기 중...", STATUS_INFO["pct"])
    return {"status": "stopping"}


@app.get("/api/status")
def get_status():
    """프론트엔드가 실시간 렌더링을 위해 주기적으로 긁어갈(Polling) 상태 엔드포인트"""
    with STATUS_LOCK:
        return STATUS_INFO


def _bg_translation_pipeline(req: TranslationRequest):
    global MODPACKS_CACHE
    CANCEL_EVENT.clear()
    try:
        with STATUS_LOCK:
            STATUS_INFO.update({
                "text": "초기화 중...", "pct": 0, "logs": [], "complete": False,
                "stopped": False, "zip_filename": "", "b64_data": "",
                "started_at": time.time(), "elapsed_seconds": 0, "eta_seconds": None,
                "processed_chunks": 0, "total_chunks": 0,
                "scan_phase": "idle", "scan_processed": 0, "scan_total": 0,
                "scan_percent": 0, "scan_eta_seconds": None,
            })

        def timing_ticker():
            while not is_cancelled():
                if STATUS_INFO["complete"]:
                    break
                update_timing_status()
                time.sleep(0.5)
            update_timing_status()

        threading.Thread(target=timing_ticker, daemon=True, name="translation-timing").start()

        config_data = load_or_setup_launcher_paths()
        config_data["saved_engine_choice"] = req.engine_choice
        config_data["saved_api_key"] = req.api_key
        config_data["saved_model_name"] = req.model_name
        config_data["saved_endpoint_url"] = (req.endpoint_url or "").strip() or DEFAULT_NLLB_ENDPOINT
        save_session(req)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

        pack_info = next((pack for pack in MODPACKS_CACHE if pack["root_path"] == req.pack_path), None)
        if pack_info is None:
            if not (0 <= req.selected_pack_idx < len(MODPACKS_CACHE)):
                raise ValueError("번역할 모드팩을 찾을 수 없습니다.")
            pack_info = MODPACKS_CACHE[req.selected_pack_idx]

        # env 파일 셋업
        lines = []
        if req.engine_choice == "2":
            lines.append(f"PAPAGO_SECRET={req.api_key}\n")
        elif req.engine_choice == "3":
            lines.append(f"OPENAI_API_KEY={req.api_key}\n")
            if req.model_name: lines.append(f"CHATGPT_MODEL={req.model_name}\n")
        elif req.engine_choice == "5":
            lines.append(f"GEMINI_API_KEY={req.api_key}\n")
            if req.model_name: lines.append(f"GEMINI_MODEL={req.model_name}\n")
        elif req.engine_choice == "6":
            if req.api_key: lines.append(f"OLLAMA_API_KEY={req.api_key}\n")
            if req.model_name: lines.append(f"OLLAMA_MODEL={req.model_name}\n")
        elif req.engine_choice == "7":
            lines.append(f"OPENROUTER_API_KEY={req.api_key}\n")
            if req.model_name: lines.append(f"OPENROUTER_MODEL={req.model_name}\n")
        elif req.engine_choice == "8":
            lines.append(f"CLAUDE_API_KEY={req.api_key}\n")
            if req.model_name: lines.append(f"CLAUDE_MODEL={req.model_name}\n")
        try:
            with open(ENV_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception:
            pass

        final_lang_code = get_final_lang_code(req.dest_lang)
        output_folder = "output"
        temp_build_folder = "temp_build"

        os.makedirs(output_folder, exist_ok=True)
        if os.path.exists(temp_build_folder): shutil.rmtree(temp_build_folder)
        os.makedirs(temp_build_folder, exist_ok=True)

        add_log("=" * 75)
        add_log(f"🔄 고속 멀티스레딩 엔진 시작 (엔진: {req.engine_choice} | {req.src_lang} -> {req.dest_lang})")

        # 📌 [수정 포인트 1] 기번역 학습 단계를 완벽히 방어적으로 격리
        set_status("⚙️ 초기화 단계: 로컬 기번역 학습 중...", 5)
        original_cwd = os.getcwd()

        local_glossary_extracted = {}

        if req.dest_lang in ["ko_kr", "ko"]:
            try:
                add_log(f"🔍 모드팩 루트 탐색 시작: {pack_info['root_path']}")
                scan_started = time.monotonic()
                last_scan_bucket = -1

                def report_scan_progress(current, total, phase):
                    nonlocal last_scan_bucket
                    elapsed = max(time.monotonic() - scan_started, 0.001)
                    percent = int((current / total) * 100) if total else 0
                    eta = round((elapsed / current) * (total - current)) if phase == "scanning" and current else None
                    with STATUS_LOCK:
                        STATUS_INFO["scan_phase"] = phase
                        STATUS_INFO["scan_processed"] = current
                        STATUS_INFO["scan_total"] = total
                        STATUS_INFO["scan_percent"] = percent
                        STATUS_INFO["scan_eta_seconds"] = eta
                    if phase == "inventory":
                        set_status(
                            f"🔍 로컬 탐색 범위 계산 중... 확인된 작업 후보 {current:,}개",
                            5,
                        )
                    elif phase == "scanning":
                        set_status(
                            f"🔍 로컬 glossary 탐색 중... {current:,}/{total:,} "
                            f"({percent}%) | 예상 남음 {eta if eta is not None else '계산 중'}초",
                            5,
                        )
                        bucket = percent // 25
                        if bucket > last_scan_bucket:
                            last_scan_bucket = bucket
                            add_log(
                                f"📊 로컬 탐색 {percent}% 완료 "
                                f"({current:,}/{total:,}, 예상 남음 {eta if eta is not None else '계산 중'}초)"
                            )
                    else:
                        set_status("✅ 로컬 glossary 탐색 완료", 5)

                # 실제 수집 dict와 탐색 진행률을 모두 백엔드 상태로 전달한다.
                local_glossary_extracted = scan_and_build_local_glossary(
                    pack_info['root_path'],
                    progress_callback=report_scan_progress,
                    cancel_event=CANCEL_EVENT,
                )
                add_log(f"✅ 로컬 기번역 데이터 학습 완료. {len(local_glossary_extracted)}개 용어 확보")
            except InterruptedError:
                raise
            except Exception as e:
                add_log(f"[경고] 기번역 학습 중 에러가 발생하여 스킵합니다 (에러: {e})")
            finally:
                os.chdir(original_cwd)  # 어떤 일이 있어도 작업 디렉토리는 원복

            try:
                from module.glossary_sync import initialize_master_glossary
                initialize_master_glossary(local_glossary_extracted)
            except Exception as e:
                add_log(f"[경고] 마스터 사전 통합 실패: {e}")
        else:
            add_log("ℹ️ 대상 언어가 한국어가 아니므로 기번역 데이터 학습을 건너뜁니다.")

        # 📌 [수정 포인트 2] 번역 엔진 빌드 및 파일 파싱 시작
        set_status("🛰️ 번역 엔진 구성 및 파일 탐색 중...", 10)

        translator, max_batch_chars = get_translator(
            req.engine_choice,
            req.src_lang,
            req.dest_lang,
            endpoint=req.endpoint_url or DEFAULT_NLLB_ENDPOINT,
            cancel_event=CANCEL_EVENT,
            log_func=add_log,
            api_key=req.api_key,
            model_name=req.model_name,
        )

        if not translator:
            add_log("❌ [오류] 번역기 엔진 빌드 실패!")
            set_status("❌ 엔진 빌드 실패", 0)
            return

        add_log("📂 번역 대상 로컬라이제이션 파일 스캔 중...")
        tasks_to_run = parse_target_localization_files(pack_info['config_path'], pack_info['root_path'], req.src_lang,
                                                       final_lang_code)
        selected_files = set(req.selected_file_paths)
        selected_mods = {m.strip().lower() for m in req.selected_mods if m.strip()}
        if selected_files:
            tasks_to_run = [task for task in tasks_to_run if task["input_path"] in selected_files]
        if selected_mods:
            tasks_to_run = [
                task for task in tasks_to_run
                if any(mod in task["input_path"].replace(os.sep, "/").lower() for mod in selected_mods)
            ]

        if not tasks_to_run:
            add_log("ℹ️ 처리 가능한 유효 언어 자원 파일이 없습니다. (경로 설정을 확인하세요)")
            set_status("ℹ️ 번역 대상 파일 없음", 0)
            return

        add_log(f"📋 총 {len(tasks_to_run)}개의 파일 리소스가 스캔되었습니다. 청크 분할 시작...")
        prepared_tasks = []
        total_chunks_count = 0
        for task in tasks_to_run:
            content, matches, skip_map = extract_strings_from_file(task['input_path'], req.skip_chapters)
            unique_matches = [t for t in set(matches) if not (req.skip_chapters and t in skip_map)]
            if task.get('existing_translations'):
                unique_matches = [m for m in unique_matches if m not in task['existing_translations']]
            chunks = build_batches(unique_matches, max_batch_chars, encode_text) if unique_matches else []
            total_chunks_count += len(chunks)
            prepared_tasks.append(
                {'task': task, 'content': content, 'matches': matches, 'skip_map': skip_map, 'chunks': chunks})

        with STATUS_LOCK:
            STATUS_INFO["total_chunks"] = total_chunks_count

        if total_chunks_count == 0:
            add_log("ℹ️ 이미 모든 문장이 번역되어 있거나 새롭게 번역할 청크가 없습니다.")
            # 파일이 아예 안 뽑혀도 빈 압축파일 방지를 위해 기존 파일 그대로 복사 복구 로직 실행
            for p_task in prepared_tasks:
                task = p_task['task']
                target_out_path = os.path.join(temp_build_folder, task['output_rel_path'])
                if not task['is_quest']:
                    target_out_path = os.path.join(os.path.dirname(target_out_path), f"{final_lang_code}{task['ext']}")
                save_translated_file(target_out_path, p_task['content'], task.get('existing_translations', {}),
                                     task['ext'])
        else:
            add_log(f"📦 총 {total_chunks_count}개의 배치가 병렬 큐에 등록되었습니다.")

        processed_chunks_count = 0
        if req.engine_choice == "4":
            max_workers = 1
        else:
            max_workers = 2 if req.engine_choice in ["2", "3"] else 6

        for p_idx, p_task in enumerate(prepared_tasks):
            task = p_task['task']
            content = p_task['content']
            matches = p_task['matches']
            skip_map = p_task['skip_map']
            chunks = p_task['chunks']  # [ [encoded_1, encoded_2], ... ]

            target_out_path = os.path.join(temp_build_folder, task['output_rel_path'])
            if not task['is_quest']:
                target_out_path = os.path.join(os.path.dirname(target_out_path), f"{final_lang_code}{task['ext']}")

            if not chunks:
                save_translated_file(target_out_path, content, task.get('existing_translations', {}), task['ext'])
                continue

            add_log(f"▶️ [{p_idx + 1}/{len(prepared_tasks)}] {task['display_name']} - {len(chunks)}개 청크 병렬 처리")

            # 📌 이 파일 전용 결과 맵 생성
            local_translated_map = dict(task.get('existing_translations', {}))

            # 번역 제외/스킵 대상 원문 그대로 채워두기 (Key는 디코딩된 원문 기준)
            for text in matches:
                if not text.strip() or text.startswith('{@') or (req.skip_chapters and text in skip_map):
                    local_translated_map[text] = text

            # 멀티스레드 완료 결과 수집을 위한 리스트
            futures = []

            # translate_batch 내부의 전역 limiter/429 backoff이 실제 호출 직전에 적용된다.
            # Google은 해당 lock과 호출 순서를 보장하기 위해 단일 워커만 사용한다.
            if req.engine_choice == "1":
                max_workers = 1
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for chunk in chunks:
                    if is_cancelled():
                        break
                    # 실패한 청크는 내부 재시도가 끝난 후 future가 완료되어 다음 청크로 진행한다.
                    future = executor.submit(
                        translate_batch, chunk, translator, decode_text,
                        CANCEL_EVENT, add_log,
                    )
                    futures.append(future)

                # 어떤 스레드가 먼저 끝나든 안전하게 수집
                for future in as_completed(futures):
                    try:
                        batch_result = future.result()  # { 원문_raw: 번역문_raw } 형태

                        if batch_result and isinstance(batch_result, dict):
                            # 📌 핵심: 이미 완벽하게 디코딩 복원된 맵이므로 그대로 병합합니다.
                            local_translated_map.update(batch_result)

                    except InterruptedError:
                        CANCEL_EVENT.set()
                        add_log("   ⏹ 현재 청크의 백오프/API 작업이 중지되었습니다.")
                    except Exception as e:
                        add_log(f"   ⚠️ 청크 번역 결과 수집 중 오류 발생: {e}")

                    processed_chunks_count += 1
                    with STATUS_LOCK:
                        STATUS_INFO["processed_chunks"] = processed_chunks_count
                    update_timing_status()
                    pct = int((processed_chunks_count / max(total_chunks_count, 1)) * 85) + 10
                    set_status(f"⚡ 번역 중 ({processed_chunks_count}/{total_chunks_count} 완료)", pct)

            if is_cancelled():
                add_log("중지 요청을 확인했습니다. 결과 압축을 생성하지 않습니다.")
                break
            # 모든 스레드가 끝난 뒤에만 파일을 기록한다.
            save_translated_file(target_out_path, content, local_translated_map, task['ext'])

        if is_cancelled():
            with STATUS_LOCK:
                STATUS_INFO["stopped"] = True
            set_status("⏹ 번역이 중지되었습니다.", STATUS_INFO["pct"])
            return

        update_timing_status()
        set_status("📦 리소스팩 패키징 ZIP 생성 중...", 95)
        clean_pack_name = re.sub(r'[\/:*?"<>| ]', '_', pack_info['name'])
        zip_filename = f"{clean_pack_name}_{datetime.now().strftime('%m%d')}_{final_lang_code}.zip"
        final_zip_path = os.path.join(output_folder, zip_filename)

        with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_build_folder):
                for file in files:
                    full_p = os.path.join(root, file)
                    zipf.write(full_p, os.path.relpath(full_p, temp_build_folder))
        shutil.rmtree(temp_build_folder)

        with open(final_zip_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        update_timing_status()
        set_status("✅ 완료되었습니다!", 100)
        add_log(f"🎉 모든 파일 빌드 완료!\n파일명: {zip_filename}")

        with STATUS_LOCK:
            STATUS_INFO["complete"] = True
            STATUS_INFO["zip_filename"] = zip_filename
            STATUS_INFO["b64_data"] = b64_data

    except Exception as e:
        if is_cancelled():
            add_log("⏹ NLLB 준비/번역 작업이 사용자의 중지 요청으로 종료되었습니다.")
            with STATUS_LOCK:
                STATUS_INFO["stopped"] = True
            set_status("⏹ 번역이 중지되었습니다.", STATUS_INFO["pct"])
        else:
            add_log(f"\n❌ [치명적 백엔드 에러]: {str(e)}")
            set_status("❌ 오류로 인하여 중단됨", 0)


@app.post("/api/start-translation")
def start_translation(req: TranslationRequest, background_tasks: BackgroundTasks):
    """번역 프로세스를 메인 스레드와 완전 무관하게 FastAPI 백그라운드 태스크로 넘깁니다."""
    background_tasks.add_task(_bg_translation_pipeline, req)
    return {"status": "started"}


if __name__ == "__main__":
    import uvicorn
    from pathlib import Path

    # 서버 기동과 동시에 감시 스레드 가동
    threading.Thread(target=_monitor_browser_closed, daemon=True).start()

    html_file_path = Path(__file__).parent / "index.html"
    html_url = html_file_path.resolve().as_uri()

    threading.Timer(1.5, lambda: webbrowser.open(html_url)).start()
    uvicorn.run(app, host="127.0.0.1", port=18443)
