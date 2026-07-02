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

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 기존 모듈 및 설정 변수 로드
from cli_translator import (
    load_or_setup_launcher_paths,
    find_modpacks_deep,
    parse_target_localization_files,
    get_final_lang_code,
    CONFIG_FILE
)

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
STATUS_INFO = {"text": "대기 중...", "pct": 0, "logs": [], "complete": False, "zip_filename": "", "b64_data": ""}
STATUS_LOCK = threading.Lock()
MODPACKS_CACHE = []


class TranslationRequest(BaseModel):
    src_lang: str
    dest_lang: str
    skip_chapters: bool
    engine_choice: str
    selected_pack_idx: int
    api_key: str
    model_name: str
    endpoint_url: str


def add_log(msg: str):
    print(msg)
    with STATUS_LOCK:
        STATUS_INFO["logs"].append(msg)


def set_status(text: str, pct: int):
    with STATUS_LOCK:
        STATUS_INFO["text"] = text
        STATUS_INFO["pct"] = pct


LAST_HEARTBEAT_TIME = time.time()


@app.post("/api/heartbeat")
def receive_heartbeat():
    """프론트엔드로부터 생존 신호를 받습니다."""
    global LAST_HEARTBEAT_TIME
    LAST_HEARTBEAT_TIME = time.time()
    return {"status": "alive"}


def _monitor_browser_closed():
    """브라우저가 닫혔는지 주기적으로 감지하여 서버를 자동 종료합니다."""
    global LAST_HEARTBEAT_TIME
    while True:
        time.sleep(2)  # 2초마다 체크
        # 마지막 신호 이후 5초 이상 응답이 없으면 모든 브라우저 창이 닫힌 것으로 간주
        if time.time() - LAST_HEARTBEAT_TIME > 5:
            print("🔌 모든 브라우저 탭이 닫힘을 감지했습니다. API 서버를 종료합니다.")

            # uvicorn 서버와 프로세스를 안전하게 종료
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
            "icon": icon_src
        })

    return {
        "config": {
            "saved_engine_choice": config_data.get("saved_engine_choice", "1"),
            "saved_api_key": config_data.get("saved_api_key", ""),
            "saved_model_name": config_data.get("saved_model_name", ""),
            "saved_endpoint_url": config_data.get("saved_endpoint_url", "http://192.168.0.35:8000/translate")
        },
        "modpacks": formatted_packs
    }


@app.get("/api/status")
def get_status():
    """프론트엔드가 실시간 렌더링을 위해 주기적으로 긁어갈(Polling) 상태 엔드포인트"""
    with STATUS_LOCK:
        return STATUS_INFO


def _bg_translation_pipeline(req: TranslationRequest):
    global MODPACKS_CACHE
    try:
        with STATUS_LOCK:
            STATUS_INFO["logs"] = []
            STATUS_INFO["complete"] = False
            STATUS_INFO["b64_data"] = ""

        config_data = load_or_setup_launcher_paths()
        config_data["saved_engine_choice"] = req.engine_choice
        config_data["saved_api_key"] = req.api_key
        config_data["saved_model_name"] = req.model_name
        config_data["saved_endpoint_url"] = req.endpoint_url
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

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

        if req.dest_lang in ["ko_kr", "ko"]:
            try:
                add_log(f"🔍 모드팩 루트 탐색 시작: {pack_info['root_path']}")
                os.chdir(pack_info['root_path'])

                # 만약 이 함수가 무겁다면 타임아웃이나 예외 발생 시 스킵되도록 조치
                scan_and_build_local_glossary()
                add_log("✅ 로컬 기번역 데이터 학습 완료.")
            except Exception as e:
                add_log(f"[경고] 기번역 학습 중 에러가 발생하여 스킵합니다 (에러: {e})")
            finally:
                os.chdir(original_cwd)  # 어떤 일이 있어도 작업 디렉토리는 원복
        else:
            add_log("ℹ️ 대상 언어가 한국어가 아니므로 기번역 데이터 학습을 건너뜁니다.")

        # 📌 [수정 포인트 2] 번역 엔진 빌드 및 파일 파싱 시작
        set_status("🛰️ 번역 엔진 구성 및 파일 탐색 중...", 10)

        translator, max_batch_chars = get_translator(req.engine_choice, req.src_lang, req.dest_lang)
        if req.engine_choice == "4" and hasattr(translator, 'endpoint'):
            translator.endpoint = req.endpoint_url.strip()

        if not translator:
            add_log("❌ [오류] 번역기 엔진 빌드 실패!")
            set_status("❌ 엔진 빌드 실패", 0)
            return

        add_log("📂 번역 대상 로컬라이제이션 파일 스캔 중...")
        tasks_to_run = parse_target_localization_files(pack_info['config_path'], pack_info['root_path'], req.src_lang,
                                                       final_lang_code)

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
        max_workers = 2 if req.engine_choice in ["2", "3"] else 6

        for p_idx, p_task in enumerate(prepared_tasks):
            task = p_task['task']
            content = p_task['content']
            matches = p_task['matches']
            skip_map = p_task['skip_map']
            chunks = p_task['chunks']

            target_out_path = os.path.join(temp_build_folder, task['output_rel_path'])
            if not task['is_quest']:
                target_out_path = os.path.join(os.path.dirname(target_out_path), f"{final_lang_code}{task['ext']}")

            if not chunks:
                save_translated_file(target_out_path, content, task.get('existing_translations', {}), task['ext'])
                continue

            add_log(f"▶️ [{p_idx + 1}/{len(prepared_tasks)}] {task['display_name']} - {len(chunks)}개 청크 병렬 처리")
            translated_map = dict(task.get('existing_translations', {}))
            for text in matches:
                if not text.strip() or text.startswith('{@') or (req.skip_chapters and text in skip_map):
                    translated_map[text] = text

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_chunk = {
                    executor.submit(translate_batch, chunk, translator, decode_text): c_idx
                    for c_idx, chunk in enumerate(chunks)
                }
                for future in as_completed(future_to_chunk):
                    c_idx = future_to_chunk[future]
                    try:
                        batch_result = future.result()
                        translated_map.update(batch_result)
                    except Exception as e:
                        add_log(f"   ⚠️ [청크 {c_idx + 1}번 오류]: {e}")

                    processed_chunks_count += 1
                    pct = int((processed_chunks_count / max(total_chunks_count, 1)) * 85) + 10
                    set_status(f"⚡ 병렬 고속 번역 중 ({processed_chunks_count}/{total_chunks_count} 완료)", pct)

            save_translated_file(target_out_path, content, translated_map, task['ext'])

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

        set_status("✅ 완료되었습니다!", 100)
        add_log(f"🎉 모든 파일 빌드 완료!\n파일명: {zip_filename}")

        with STATUS_LOCK:
            STATUS_INFO["complete"] = True
            STATUS_INFO["zip_filename"] = zip_filename
            STATUS_INFO["b64_data"] = b64_data

    except Exception as e:
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
