import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from datetime import datetime

# HTML GUI 브릿지 라이브러리
import webview

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


class WebGUIBridge:
    """HTML/JS(프론트엔드)와 Python(백엔드) 간의 실시간 데이터 연동을 담당하는 브릿지 클래스"""

    def __init__(self):
        self.window = None
        self.config_data = {}
        self.modpacks_data = []

    def log_to_html(self, message):
        """웹 UI 콘솔창으로 메시지 실시간 전송"""
        if self.window:
            # 자바스크립트의 안전한 이스케이프 처리를 위해 json.dumps 사용
            safe_msg = json.dumps(message)
            self.window.evaluate_js(f"appendLog({safe_msg});")

    def update_status_to_html(self, text, pct=0):
        """웹 UI 하단 상태바 및 프로그레스바 동기화"""
        if self.window:
            safe_text = json.dumps(text)
            self.window.evaluate_js(f"updateStatus({safe_text}, {pct});")

    def init_app(self):
        """앱 기동 시 HTML 내부로 기존 설정 데이터 및 모드팩 정보 자동 주입"""
        self.config_data = load_or_setup_launcher_paths()

        # 저장된 엔진 및 키셋 방어선 구축
        saved_config = {
            "launcher_paths": {
                "CurseForge": self.config_data.get("CurseForge", ""),
                "Prism": self.config_data.get("Prism Launcher", ""),
                "Modrinth": self.config_data.get("Modrinth App", "")
            },
            "saved_engine_choice": self.config_data.get("saved_engine_choice", "1"),
            "saved_api_key": self.config_data.get("saved_api_key", ""),
            "saved_model_name": self.config_data.get("saved_model_name", ""),
            "saved_endpoint_url": self.config_data.get("saved_endpoint_url", "http://192.168.0.35:8000/translate")
        }

        # 런처 자동 스캔 진행
        try:
            self.modpacks_data = find_modpacks_deep(self.config_data)
        except Exception as e:
            self.modpacks_data = []

        # 웹 프론트엔드로 로드 결과 일괄 전송 초기화
        if self.window:
            self.window.evaluate_js(
                f"onBackendConfigLoaded({json.dumps(saved_config)}, {json.dumps(self.modpacks_data)});")

    def save_config_from_html(self, updated_config_js):
        """웹 브라우저단에서 키 입력이나 경로 변경 발생 시 실시간 동기화 저장"""
        try:
            data = json.loads(updated_config_js)
            self.config_data["saved_engine_choice"] = data.get("saved_engine_choice", "1")
            self.config_data["saved_api_key"] = data.get("saved_api_key", "")
            self.config_data["saved_model_name"] = data.get("saved_model_name", "")
            self.config_data["saved_endpoint_url"] = data.get("saved_endpoint_url", "")

            # 런처 패스 업데이트
            paths = data.get("launcher_paths", {})
            self.config_data["CurseForge"] = paths.get("CurseForge", "")
            self.config_data["Prism Launcher"] = paths.get("Prism", "")
            self.config_data["Modrinth App"] = paths.get("Modrinth", "")

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def browse_folder(self, launcher_key):
        """웹에서 '변경' 버튼 클릭 시 파이썬 고유 디렉토리 탐색기 오픈"""
        chosen_dir = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if chosen_dir:
            path_str = os.path.normpath(chosen_dir[0])
            # 다시 스캔하여 최신 리스트와 함께 경로 반환
            if launcher_key == "CurseForge":
                self.config_data["CurseForge"] = path_str
            elif launcher_key == "Prism":
                self.config_data["Prism Launcher"] = path_str
            elif launcher_key == "Modrinth":
                self.config_data["Modrinth App"] = path_str

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=4)

            self.modpacks_data = find_modpacks_deep(self.config_data)
            return json.dumps({"status": "success", "path": path_str, "modpacks": self.modpacks_data})
        return json.dumps({"status": "cancel"})

    def start_translation_pipeline(self, request_data_js):
        """번역 시작 신호를 받으면 백그라운드 스레드로 연산 코어 기동"""
        req_data = json.loads(request_data_js)
        threading.Thread(target=self._run_translation_core, args=(req_data,), daemon=True).start()

    def _run_translation_core(self, req_data):
        try:
            src_lang = req_data.get("src_lang", "en")
            dest_lang = req_data.get("dest_lang", "ko")
            skip_chapters = req_data.get("skip_chapters", True)
            choice = req_data.get("engine_choice", "1")
            selected_idx = req_data.get("selected_pack_idx")

            if selected_idx is None or selected_idx >= len(self.modpacks_data):
                self.window.evaluate_js("alert('번역 대상 모드팩 인스턴스가 올바르지 않습니다.');")
                self.window.evaluate_js("toggleUIProcessing(false);")
                return

            pack_info = self.modpacks_data[selected_idx]

            # api.env 가상 파일 연동 동기화
            lines = []
            api_key = self.config_data.get("saved_api_key", "")
            model_name = self.config_data.get("saved_model_name", "").strip()
            if choice == "2":
                lines.append(f"PAPAGO_SECRET={api_key}\n")
            elif choice == "3":
                lines.append(f"OPENAI_API_KEY={api_key}\n")
                if model_name: lines.append(f"CHATGPT_MODEL={model_name}\n")
            elif choice == "5":
                lines.append(f"GEMINI_API_KEY={api_key}\n")
                if model_name: lines.append(f"GEMINI_MODEL={model_name}\n")
            try:
                with open(ENV_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            except Exception:
                pass

            final_lang_code = get_final_lang_code(dest_lang)
            output_folder = "output"
            temp_build_folder = "temp_build"

            os.makedirs(output_folder, exist_ok=True)
            if os.path.exists(temp_build_folder): shutil.rmtree(temp_build_folder)
            os.makedirs(temp_build_folder, exist_ok=True)

            self.log_to_html("=" * 75)
            self.log_to_html(f"🔄 웹 제어 엔진 연동 완수 -> 번역 파이프라인 기동 (엔진: {choice} | {src_lang} -> {dest_lang})")

            # 1. 로컬 기번역 기계학습
            self.update_status_to_html("⚙️ 초기화 단계: 로컬 기번역 사전 탐색 및 학습 중...", 3)
            original_cwd = os.getcwd()
            try:
                os.chdir(pack_info['root_path'])
                if dest_lang in ["ko_kr", "ko"]: scan_and_build_local_glossary()
            except Exception as e:
                self.log_to_html(f"[경고] 로컬 번역 병합 스킵: {e}")
            finally:
                os.getcwd(); os.chdir(original_cwd)

            # 2. 엔진 인스턴스 핸들링
            if choice == "4" and self.config_data.get("saved_endpoint_url", "").strip():
                translator, max_batch_chars = get_translator(choice, src_lang, dest_lang)
                if translator and hasattr(translator, 'endpoint'):
                    translator.endpoint = self.config_data.get("saved_endpoint_url", "").strip()
            else:
                translator, max_batch_chars = get_translator(choice, src_lang, dest_lang)

            if not translator:
                self.log_to_html("❌ [오류] 번역기 엔진 빌드 실패! 설정을 재조정하세요.")
                self.update_status_to_html("❌ 엔진 빌드 에러", 0)
                self.window.evaluate_js("toggleUIProcessing(false);")
                return

            # 3. 타겟 자원 파일 파싱
            tasks_to_run = parse_target_localization_files(pack_info['config_path'], pack_info['root_path'], src_lang,
                                                           final_lang_code)
            if not tasks_to_run:
                self.log_to_html("ℹ️ 처리 가능한 유효 언어 리소스 파일(.json / .snbt)이 검출되지 않았습니다.")
                if os.path.exists(temp_build_folder): shutil.rmtree(temp_build_folder)
                self.update_status_to_html("ℹ️ 번역 대상 리소스 없음", 100)
                self.window.evaluate_js("toggleUIProcessing(false);")
                return

            self.update_status_to_html("📋 분석 단계: 대량 배치 사전 컴파일 및 청크 계산 중...", 5)
            prepared_tasks = []
            total_chunks_count = 0

            for task in tasks_to_run:
                content, matches, skip_map = extract_strings_from_file(task['input_path'], skip_chapters)
                unique_matches = [t for t in set(matches) if not (skip_chapters and t in skip_map)]
                existing_translations = task.get('existing_translations', {})
                if existing_translations:
                    unique_matches = [m for m in unique_matches if m not in existing_translations]

                chunks = build_batches(unique_matches, max_batch_chars, encode_text) if unique_matches else []
                total_chunks_count += len(chunks)
                prepared_tasks.append(
                    {'task': task, 'content': content, 'matches': matches, 'skip_map': skip_map, 'chunks': chunks})

            self.log_to_html(f"📦 분석 완료: 총 {len(tasks_to_run)}개 파일에서 [{total_chunks_count}]개의 네트워크 전송 청크 배치가 생성되었습니다.")

            processed_chunks_count = 0
            start_time = time.time()

            # 4. 핵심 번역 루프 실행
            for p_idx, p_task in enumerate(prepared_tasks):
                task = p_task['task']
                content = p_task['content']
                matches = p_task['matches']
                skip_map = p_task['skip_map']
                chunks = p_task['chunks']

                target_out_path = os.path.join(temp_build_folder, task['output_rel_path'])
                if not task['is_quest']:
                    dir_name = os.path.dirname(target_out_path)
                    target_out_path = os.path.join(dir_name, f"{final_lang_code}{task['ext']}")

                existing_translations = task.get('existing_translations', {})
                if not chunks:
                    save_translated_file(target_out_path, content, existing_translations, task['ext'])
                    continue

                self.log_to_html(
                    f"▶️ [{p_idx + 1}/{len(prepared_tasks)}] {task['display_name']} ({len(chunks)} 청크 처리 시작)")
                translated_map = dict(existing_translations)
                for text in matches:
                    if not text.strip() or text.startswith('{@') or (skip_chapters and text in skip_map):
                        translated_map[text] = text

                for c_idx, chunk in enumerate(chunks):
                    batch_result = translate_batch(chunk, translator, decode_text)
                    translated_map.update(batch_result)

                    processed_chunks_count += 1
                    current_pct = int((processed_chunks_count / max(total_chunks_count, 1)) * 90) + 5  # 5%~95% 구간 할당

                    elapsed = time.time() - start_time
                    avg_time = elapsed / processed_chunks_count
                    eta = int(avg_time * (total_chunks_count - processed_chunks_count))
                    eta_str = f"| ⏳ 남은시간: 약 {eta // 60}분 {eta % 60}초"

                    self.update_status_to_html(
                        f"⚡ 진행률: {int((processed_chunks_count / total_chunks_count) * 100)}% ({processed_chunks_count}/{total_chunks_count} 청크 전송 완료) {eta_str}",
                        current_pct)
                    self.log_to_html(f"   ↳ 청크 처리 중 [{c_idx + 1}/{len(chunks)}] - 전송 완수")

                save_translated_file(target_out_path, content, translated_map, task['ext'])

            # 5. 최종 리소스팩 패키징 빌드
            self.update_status_to_html("📦 100% 번역 완수! 최종 배포 리소스팩(ZIP) 패키징 단계 진입...", 95)
            clean_pack_name = re.sub(r'[\/:*?"<>| ]', '_', pack_info['name'])
            date_str = datetime.now().strftime("%m%d")
            zip_filename = f"{clean_pack_name}_{date_str}_{final_lang_code}.zip"
            final_zip_path = os.path.join(output_folder, zip_filename)

            self.log_to_html(f"\n📦 후처리 배포 팩 압축 생성 중 -> {zip_filename}")
            with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_build_folder):
                    for file in files:
                        full_p = os.path.join(root, file)
                        zipf.write(full_p, os.path.relpath(full_p, temp_build_folder))

            shutil.rmtree(temp_build_folder)
            total_elapsed = time.time() - start_time

            self.log_to_html(f"============================================================")
            self.log_to_html(f"🎉 리소스팩 패키징 완수! 총 {int(total_elapsed // 60)}분 {int(total_elapsed % 60)}초가 소요되었습니다.")
            self.log_to_html(f"➔ 파일 저장 절대 경로: {os.path.abspath(final_zip_path)}")
            self.log_to_html(f"============================================================")

            self.update_status_to_html("✅ 모든 작업이 완벽하게 완료되었습니다!", 100)
            self.window.evaluate_js(f"alert('번역 및 리소스팩 패키징이 성공적으로 끝났습니다!\\n\\n결과물: {zip_filename}');")
            self.window.evaluate_js("toggleUIProcessing(false);")

        except Exception as e:
            self.log_to_html(f"\n❌ [오류 발생으로 인한 작업 중단]: {str(e)}")
            self.update_status_to_html("❌ 번역 파이프라인 중단 에러 발생", 0)
            self.window.evaluate_js(f"alert('작업 도중 에러가 발생했습니다:\\n{str(e)}');")
            self.window.evaluate_js("toggleUIProcessing(false);")


if __name__ == "__main__":
    bridge = WebGUIBridge()
    # 로컬 HTML 파일을 로드하여 런처 구동 창 생성 (기본 크기 지정)
    window = webview.create_window(
        title="Minecraft Modpack High-Speed Web Translator",
        url="index.html",
        js_api=bridge,
        width=880,
        height=800,
        min_size=(820, 720)
    )
    bridge.window = window

    # 윈도우가 완전히 준비되면 초기 구성값 로딩 트리거 기동
    webview.start(bridge.init_app)
