import json
import os
import re
import shutil
import sys
import threading
import time
# GUI 관련 라이브러리
import tkinter as tk
import zipfile
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

# [로직 유지] 기존 파일들로부터 환경 설정 변수 및 핵심 함수 로드
from cli_translator import (
    load_or_setup_launcher_paths,
    find_modpacks_deep,
    parse_target_localization_files,
    get_final_lang_code,
    CONFIG_FILE,
    LANG_MENU
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
except ImportError as e:
    print(f"❌ [오류] 'module' 패키지를 로드할 수 없습니다: {e}")
    sys.exit(1)


class MinecraftTranslatorGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Minecraft Modpack High-Speed Translator (GUI)")
        self.geometry("820x800")
        self.minimum_size = (750, 720)

        self.modpacks_data = []
        self.selected_pack_info = None
        self.launcher_paths = {}

        self.setup_styles()
        self.create_widgets()

        # 런처 경로 세팅 및 모드팩 자동 스캔
        self.init_launcher_paths_and_scan()

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure(".", font=("Malgun Gothic", 10))
        self.style.configure("TLabelframe", padding=10)
        self.style.configure("TLabelframe.Label", font=("Malgun Gothic", 11, "bold"), foreground="#2c3e50")
        self.style.configure("TButton", font=("Malgun Gothic", 10, "bold"), padding=4)

        # 하단 번역 시작 버튼 전용 강조 스타일 (Blue Accent)
        self.style.configure("Action.TButton", font=("Malgun Gothic", 12, "bold"), background="#3498db",
                             foreground="white")
        self.style.map("Action.TButton", background=[("active", "#2980b9")])

    def create_widgets(self):
        main_container = ttk.Frame(self, padding=10)
        main_container.pack(fill="both", expand=True)

        # ==========================================
        # 상단 영역: 1. 번역기 엔진 & 2. 옵션 및 언어 설정
        # ==========================================
        top_frame = ttk.Frame(main_container)
        top_frame.pack(fill="x", side="top", pady=(0, 5))

        # 1. 번역기 엔진 선택 (좌측)
        engine_lf = ttk.LabelFrame(top_frame, text=" 1. 번역기 엔진 선택 ")
        engine_lf.pack(fill="both", expand=True, side="left", padx=(0, 5))

        self.engine_var = tk.StringVar(value="5")  # 기본값 Gemini(5)
        engines = [
            ("Google (무료)", "1"), ("Papago", "2"),
            ("ChatGPT", "3"), ("나만의 로컬 NLLB", "4"), ("Gemini (추천)", "5")
        ]
        for text, val in engines:
            rb = ttk.Radiobutton(engine_lf, text=text, value=val, variable=self.engine_var)
            rb.pack(anchor="w", pady=3, padx=5)

        # 2. 언어 및 작업 옵션 (우측 - 드롭다운 메뉴 적용)
        opt_lf = ttk.LabelFrame(top_frame, text=" 2. 언어 및 작업 옵션 ")
        opt_lf.pack(fill="both", expand=True, side="right", padx=(5, 0))

        form_frame = ttk.Frame(opt_lf)
        form_frame.pack(fill="x", anchor="n", pady=5)

        lang_options = [f"{v[0]} ({v[1]})" for v in LANG_MENU.values()]

        ttk.Label(form_frame, text="출발 언어 선택:").grid(row=0, column=0, sticky="w", pady=5, padx=5)
        self.src_lang_combo = ttk.Combobox(form_frame, values=lang_options, width=18, state="readonly")
        self.src_lang_combo.set("영어 (en)")
        self.src_lang_combo.grid(row=0, column=1, sticky="w", pady=5, padx=5)

        ttk.Label(form_frame, text="도착 언어 선택:").grid(row=1, column=0, sticky="w", pady=5, padx=5)
        self.dest_lang_combo = ttk.Combobox(form_frame, values=lang_options, width=18, state="readonly")
        self.dest_lang_combo.set("한국어 (ko)")
        self.dest_lang_combo.grid(row=1, column=1, sticky="w", pady=5, padx=5)

        self.skip_chapters_var = tk.BooleanVar(value=True)
        cb_skip = ttk.Checkbutton(opt_lf, text="퀘스트 챕터명 및 그룹 번역 제외 (추천)", variable=self.skip_chapters_var)
        cb_skip.pack(anchor="w", pady=8, padx=5)

        # ==========================================
        # 중간 영역 1: 런처 탐색 경로 설정 및 영구 저장 기능
        # ==========================================
        path_lf = ttk.LabelFrame(main_container, text=" 런처 인스턴스 탐색 경로 설정 (수정 시 자동 저장) ")
        path_lf.pack(fill="x", pady=5)

        cf_frame = ttk.Frame(path_lf)
        cf_frame.pack(fill="x", pady=2)
        ttk.Label(cf_frame, text="CurseForge:", width=13, anchor="e").pack(side="left", padx=5)
        self.cf_path_var = tk.StringVar()
        ttk.Entry(cf_frame, textvariable=self.cf_path_var).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(cf_frame, text="변경", width=5,
                   command=lambda: self.browse_launcher_path("CurseForge", self.cf_path_var)).pack(side="right", padx=5)

        pm_frame = ttk.Frame(path_lf)
        pm_frame.pack(fill="x", pady=2)
        ttk.Label(pm_frame, text="Prism:", width=13, anchor="e").pack(side="left", padx=5)
        self.pm_path_var = tk.StringVar()
        ttk.Entry(pm_frame, textvariable=self.pm_path_var).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(pm_frame, text="변경", width=5,
                   command=lambda: self.browse_launcher_path("Prism Launcher", self.pm_path_var)).pack(side="right",
                                                                                                       padx=5)

        mr_frame = ttk.Frame(path_lf)
        mr_frame.pack(fill="x", pady=2)
        ttk.Label(mr_frame, text="Modrinth:", width=13, anchor="e").pack(side="left", padx=5)
        self.mr_path_var = tk.StringVar()
        ttk.Entry(mr_frame, textvariable=self.mr_path_var).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(mr_frame, text="변경", width=5,
                   command=lambda: self.browse_launcher_path("Modrinth App", self.mr_path_var)).pack(side="right",
                                                                                                     padx=5)

        # ==========================================
        # 중간 영역 2: 3. 대상 모드팩 및 인스턴스 선택
        # ==========================================
        pack_lf = ttk.LabelFrame(main_container, text=" 3. 대상 모드팩 및 인스턴스 선택 ", padding=5)
        pack_lf.pack(fill="both", expand=True, pady=5)

        list_frame = ttk.Frame(pack_lf)
        list_frame.pack(fill="both", expand=True, pady=(0, 5))

        self.pack_listbox = tk.Listbox(
            list_frame,
            font=("Consolas" if os.name == 'nt' else "Courier", 10),
            selectmode="browse", bd=1, relief="solid"
        )
        self.pack_listbox.pack(fill="both", expand=True, side="left")
        self.pack_listbox.bind("<<ListboxSelect>>", self.on_pack_select)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.pack_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.pack_listbox.config(yscrollcommand=scrollbar.set)

        path_btn_frame = ttk.Frame(pack_lf)
        path_btn_frame.pack(fill="x", pady=2)
        ttk.Button(path_btn_frame, text="🔄 런처 재스캔 및 목록 갱신", command=self.scan_modpacks, width=22).pack(side="left",
                                                                                                       padx=2)
        ttk.Button(path_btn_frame, text="📂 커스텀 모드팩 폴더 수동 지정...", command=self.browse_custom_path).pack(side="right",
                                                                                                       padx=2)

        # ==========================================
        # 하단 영역: 실시간 로그 콘솔 및 상태바
        # ==========================================

        progress_frame = ttk.Frame(main_container)
        progress_frame.pack(fill="x", side="bottom", pady=5)

        self.status_label = ttk.Label(progress_frame, text="대기 중... (준비 완료)", font=("Malgun Gothic", 10, "bold"),
                                      foreground="#2980b9")
        self.status_label.pack(anchor="w", pady=(0, 2))

        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", pady=(0, 5))

        self.run_btn = ttk.Button(
            progress_frame,
            text="🚀 초고속 자동 번역 및 리소스팩 패키징 시작",
            style="Action.TButton",
            command=self.start_translation_thread
        )
        self.run_btn.pack(fill="x", ipady=6)

        log_lf = ttk.LabelFrame(main_container, text=" 실시간 진행 로그 콘솔 ", padding=5)
        log_lf.pack(fill="both", expand=True, pady=5)

        self.log_text = tk.Text(
            log_lf, background="#1e1e1e", foreground="#d4d4d4",
            insertbackground="white", font=("Consolas", 9), state="disabled", wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, side="left")

        log_scroll = ttk.Scrollbar(log_lf, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=log_scroll.set)

    def append_log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.update_idletasks()

    def update_status(self, text):
        self.status_label.config(text=text)
        self.update_idletasks()

    def init_launcher_paths_and_scan(self):
        self.launcher_paths = load_or_setup_launcher_paths()
        self.cf_path_var.set(self.launcher_paths.get("CurseForge", ""))
        self.pm_path_var.set(self.launcher_paths.get("Prism Launcher", ""))
        self.mr_path_var.set(self.launcher_paths.get("Modrinth App", ""))
        self.scan_modpacks()

    def browse_launcher_path(self, launcher_name, text_var):
        chosen_dir = filedialog.askdirectory(title=f"[{launcher_name}] 기본 인스턴스/프로필 폴더 선택")
        if chosen_dir:
            chosen_dir = os.path.normpath(chosen_dir)
            text_var.set(chosen_dir)
            self.launcher_paths[launcher_name] = chosen_dir
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.launcher_paths, f, ensure_ascii=False, indent=4)
                self.append_log(f"💾 [{launcher_name}] 탐색 경로가 변경 및 자동 저장되었습니다.")
                self.scan_modpacks()
            except Exception as e:
                self.append_log(f"⚠️ 설정 파일 저장 실패: {e}")

    def scan_modpacks(self):
        self.pack_listbox.delete(0, tk.END)
        try:
            self.modpacks_data = find_modpacks_deep(self.launcher_paths)
            for pack in self.modpacks_data:
                self.pack_listbox.insert(tk.END, f" [{pack['launcher']}]  {pack['name']}")
            self.append_log(f"ℹ️ 모드팩 스캔 완료: 총 {len(self.modpacks_data)}개의 인스턴스가 확인되었습니다.")
        except Exception as e:
            self.append_log(f"⚠️ 모드팩 자동 스캔 중 예외 발생: {e}")

    def on_pack_select(self, event):
        selection = self.pack_listbox.curselection()
        if selection:
            idx = selection[0]
            if idx < len(self.modpacks_data):
                self.selected_pack_info = self.modpacks_data[idx]
                self.append_log(f"🎯 작업 타겟 지정 완료 -> {self.selected_pack_info['name']}")

    def browse_custom_path(self):
        custom_path = filedialog.askdirectory(title="번역할 모드팩 루트 혹은 .minecraft 폴더를 선택하세요.")
        if not custom_path:
            return

        config_path = os.path.join(custom_path, "config")
        if not os.path.exists(config_path) and os.path.exists(os.path.join(custom_path, ".minecraft", "config")):
            config_path = os.path.join(custom_path, ".minecraft", "config")
            custom_path = os.path.join(custom_path, ".minecraft")
        elif not os.path.exists(config_path) and os.path.exists(os.path.join(custom_path, "minecraft", "config")):
            config_path = os.path.join(custom_path, "minecraft", "config")
            custom_path = os.path.join(custom_path, "minecraft")

        self.selected_pack_info = {
            "launcher": "Custom",
            "name": os.path.basename(custom_path.rstrip("\\/")),
            "root_path": custom_path,
            "config_path": config_path
        }
        self.modpacks_data.append(self.selected_pack_info)
        self.pack_listbox.insert(tk.END, f" [Custom]  {self.selected_pack_info['name']} (수동 지정)")
        self.pack_listbox.select_clear(0, tk.END)
        self.pack_listbox.select_set(tk.END)
        self.append_log(f"📂 수동 지정 인스턴스 추가 완료: {custom_path}")

    def start_translation_thread(self):
        if not self.selected_pack_info:
            messagebox.showwarning("대상 미선택", "번역 작업을 시작할 모드팩 인스턴스를 목록에서 클릭해 주세요.")
            return

        self.run_btn.config(state="disabled")
        translation_worker = threading.Thread(target=self.run_translation_logic, daemon=True)
        translation_worker.start()

    def run_translation_logic(self):
        try:
            src_match = re.search(r'\(([^)]+)\)', self.src_lang_combo.get())
            dest_match = re.search(r'\(([^)]+)\)', self.dest_lang_combo.get())

            src_lang = src_match.group(1) if src_match else "en"
            dest_lang = dest_match.group(1) if dest_match else "ko"
            skip_chapters = self.skip_chapters_var.get()
            choice = self.engine_var.get()

            final_lang_code = get_final_lang_code(dest_lang)
            output_folder = "output"
            temp_build_folder = "temp_build"

            os.makedirs(output_folder, exist_ok=True)
            if os.path.exists(temp_build_folder):
                shutil.rmtree(temp_build_folder)
            os.makedirs(temp_build_folder, exist_ok=True)

            self.append_log("\n" + "=" * 60)
            self.append_log(f"🔄 번역 파이프라인 시작 (엔진 번호: {choice} | {src_lang} -> {dest_lang})")

            # 1. 로컬 기번역 캐시 수집 코어 작동
            self.update_status("⚙️ 초기화 단계: 로컬 기번역 탐색 및 학습 중...")
            original_cwd = os.getcwd()
            try:
                os.chdir(self.selected_pack_info['root_path'])
                if dest_lang in ["ko_kr", "ko"]:
                    scan_and_build_local_glossary()
            except Exception as e:
                self.append_log(f"[경고] 로컬 번역 병합 스킵: {e}")
            finally:
                os.chdir(original_cwd)

            # 2. 번역 엔진 인스턴스 빌딩
            translator, max_batch_chars = get_translator(choice, src_lang, dest_lang)
            if not translator:
                self.append_log("❌ [오류] 번역 엔진 빌드 실패 (API Key 혹은 설정을 확인하세요)")
                self.run_btn.config(state="normal")
                self.update_status("❌ 엔진 빌드 실패")
                return

            # 3. 대상 리소스 파일 1차 스캔
            tasks_to_run = parse_target_localization_files(
                self.selected_pack_info['config_path'], self.selected_pack_info['root_path'], src_lang, final_lang_code
            )

            if not tasks_to_run:
                self.append_log("ℹ️ [안내] 처리 가능한 유효 언어 리소스 파일(.json / .snbt)이 존재하지 않습니다.")
                if os.path.exists(temp_build_folder):
                    shutil.rmtree(temp_build_folder)
                self.run_btn.config(state="normal")
                self.update_status("ℹ️ 유효한 번역 자원 없음")
                return

            # =========================================================================
            # 📌 [개선된 핵심 로직] 작업을 즉시 진행하지 않고, 모든 파일의 배치(Chunk) 선행 구성
            # =========================================================================
            self.update_status("📋 분석 단계: 대량 배치 사전 컴파일 및 청크 계산 중...")
            self.append_log("ℹ️ 모든 리소스 파일로부터 추출할 전체 배치 구조를 파악하고 있습니다...")

            prepared_tasks = []
            total_chunks_count = 0

            for task in tasks_to_run:
                content, matches, skip_map = extract_strings_from_file(task['input_path'], skip_chapters)
                unique_matches = [t for t in set(matches) if not (skip_chapters and t in skip_map)]

                existing_translations = task.get('existing_translations', {})
                if existing_translations:
                    unique_matches = [m for m in unique_matches if m not in existing_translations]

                # 새로 번역할 문장이 있을 때만 배치 청크를 분할 연산
                chunks = []
                if unique_matches:
                    chunks = build_batches(unique_matches, max_batch_chars, encode_text)

                total_chunks_count += len(chunks)

                # 가공에 필요한 파싱 원본 데이터 패킹 보관
                prepared_tasks.append({
                    'task': task,
                    'content': content,
                    'matches': matches,
                    'skip_map': skip_map,
                    'unique_matches': unique_matches,
                    'chunks': chunks
                })

            self.append_log(f"📦 분석 완료: 총 {len(tasks_to_run)}개 파일에서 총 [{total_chunks_count}]개의 API 전송 배치가 빌드되었습니다.")

            # 프로그레스바 기준을 '파일 단위'가 아닌 '전체 배치(청크) 단위'로 전격 교체
            self.progress_bar["maximum"] = max(total_chunks_count, 1)
            self.progress_bar["value"] = 0

            # 📌 정밀 시간 측정을 위한 타이머 구동
            processed_chunks_count = 0
            start_time = time.time()

            # 4. 순수 대량 치환/번역 작업 루프 시작
            for p_idx, p_task in enumerate(prepared_tasks):
                task = p_task['task']
                content = p_task['content']
                matches = p_task['matches']
                skip_map = p_task['skip_map']
                unique_matches = p_task['unique_matches']
                chunks = p_task['chunks']

                target_out_path = os.path.join(temp_build_folder, task['output_rel_path'])
                if not task['is_quest']:
                    dir_name = os.path.dirname(target_out_path)
                    target_out_path = os.path.join(dir_name, f"{final_lang_code}{task['ext']}")

                existing_translations = task.get('existing_translations', {})

                # 번역할 청크가 애초에 없는 파일(이미 기번역 완수 등) 처리
                if not chunks:
                    save_translated_file(target_out_path, content, existing_translations, task['ext'])
                    continue

                self.append_log(
                    f"▶️ [{p_idx + 1}/{len(prepared_tasks)}] {task['display_name']} ({len(chunks)}개 청크 순차 전송)")

                translated_map = dict(existing_translations)
                for text in matches:
                    if not text.strip() or text.startswith('{@') or (skip_chapters and text in skip_map):
                        translated_map[text] = text

                # 실시간 청크 전송 루프
                for c_idx, chunk in enumerate(chunks):
                    # 배치 번역 API 통신 실행
                    batch_result = translate_batch(chunk, translator, decode_text)
                    translated_map.update(batch_result)

                    # 카운터 갱신 및 정보 계산
                    processed_chunks_count += 1
                    self.progress_bar["value"] = processed_chunks_count

                    # 📌 전체 배치를 기반으로 정밀한 퍼센트(%) 및 예상 남은 시간 연산
                    current_pct = int((processed_chunks_count / total_chunks_count) * 100)
                    elapsed_time = time.time() - start_time

                    avg_time_per_chunk = elapsed_time / processed_chunks_count
                    remaining_chunks = total_chunks_count - processed_chunks_count
                    eta_seconds = int(avg_time_per_chunk * remaining_chunks)

                    eta_min = eta_seconds // 60
                    eta_sec = eta_seconds % 60
                    eta_str = f"| ⏳ 남은 시간: 약 {eta_min}분 {eta_sec}초"

                    # 상태창 동기화 피드백
                    self.update_status(
                        f"⚡ 진행률: {current_pct}% ({processed_chunks_count}/{total_chunks_count} 배치 완료) {eta_str}")
                    self.append_log(f"   ↳ 청크 처리 중 [{c_idx + 1}/{len(chunks)}] - 완료")

                # 한 파일의 모든 청크 처리가 끝나면 디스크 세이브
                save_translated_file(target_out_path, content, translated_map, task['ext'])

            # ==========================================
            # 5. 빌드 완료 데이터 최종 ZIP 리소스팩 배포 패키징
            # ==========================================
            self.update_status("📦 100% 번역 완수! 리소스 팩 패키징 완료 단계 진입...")
            clean_pack_name = re.sub(r'[\/:*?"<>| ]', '_', self.selected_pack_info['name'])
            date_str = datetime.now().strftime("%m%d")
            zip_filename = f"{clean_pack_name}_{date_str}_{final_lang_code}.zip"
            final_zip_path = os.path.join(output_folder, zip_filename)

            self.append_log(f"\n📦 후처리: 임시 데이터 구조를 통합 배포 리소스팩(ZIP)으로 압축 중...")
            with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_build_folder):
                    for file in files:
                        full_file_path = os.path.join(root, file)
                        archive_name = os.path.relpath(full_file_path, temp_build_folder)
                        zipf.write(full_file_path, archive_name)

            shutil.rmtree(temp_build_folder)

            # 최종 정산 완료 세팅
            self.progress_bar["value"] = total_chunks_count
            total_elapsed = time.time() - start_time
            t_min = int(total_elapsed // 60)
            t_sec = int(total_elapsed % 60)

            self.update_status(f"✅ 총 작업 완수 (소요시간: {t_min}분 {t_sec}초)")

            self.append_log(f"============================================================")
            self.append_log(f"🎉 리소스팩 패키징 완수! 총 {t_min}분 {t_sec}초가 소요되었습니다.")
            self.append_log(f"➔ 저장 경로: {os.path.abspath(final_zip_path)}")
            self.append_log(f"============================================================")

            self.run_btn.config(state="normal")
            messagebox.showinfo("완료", f"배포용 리소스팩 패키징 작업이 정상 완료되었습니다!\n\n결과물: {zip_filename}")

        except Exception as e:
            self.append_log(f"\n❌ [오류 발생으로 인한 작업 중단]: {str(e)}")
            self.run_btn.config(state="normal")
            self.update_status("❌ 작업 중단 오류 발생")
            messagebox.showerror("번역 실패", f"작업 도중 오류가 발생했습니다:\n{str(e)}")


if __name__ == "__main__":
    app = MinecraftTranslatorGUI()
    app.mainloop()
