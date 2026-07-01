# main.py (GUI 전용 진입점)
import os
import re
import shutil
import sys
import threading
# GUI 관련 라이브러리
import tkinter as tk
import zipfile
from datetime import datetime
from tkinter import ttk, messagebox, scrolledtext

from PIL import Image, ImageTk  # pip install Pillow 필요

# 분리된 커스텀 처리 모듈 로드
from utils import (
    get_final_lang_code,
    load_or_setup_launcher_paths,
    find_modpacks_deep,
    parse_target_localization_files,
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
        translate_batch
    )
except ImportError as e:
    print(f"\n❌ [오류] 기존 'module' 폴더 스크립트 로드 실패: {e}")
    sys.exit(1)


# =====================================================================
# 1. GUI 하단 실시간 로그 동기화 텍스트 리다이렉터
# =====================================================================
class TextRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, str_text):
        self.text_widget.insert(tk.END, str_text)
        self.text_widget.see(tk.END)

    def flush(self):
        pass


# =====================================================================
# 2. 메인 GUI 클래스 정의
# =====================================================================
class TranslatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("초고속 멀티 엔진 자동 번역기 (로컬 NLLB & Gemini 호환)")
        self.root.geometry("900x750")

        self.modpacks = []
        self.selected_pack = None
        self.pack_images = {}  # 가비지 컬렉션 방지용 이미지 캐시

        self.setup_styles()
        self.build_ui()
        self.refresh_modpacks()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TLabel', font=('Malgun Gothic', 10))
        style.configure('Header.TLabel', font=('Malgun Gothic', 12, 'bold'))
        style.configure('Title.TLabel', font=('Malgun Gothic', 14, 'bold'), foreground='#2E7D32')
        style.configure('Card.TFrame', background='#E8F5E9', borderwidth=1, relief='raised')

    def build_ui(self):
        # 상단 타이틀 및 엔진/언어 설정 영역
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top_frame, text="Minecraft Modpack Multi-Engine Translator", style='Title.TLabel').grid(row=0,
                                                                                                          column=0,
                                                                                                          columnspan=4,
                                                                                                          pady=5,
                                                                                                          sticky='w')

        # 번역 엔진 선택 드롭다운
        ttk.Label(top_frame, text="번역 엔진:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
        self.engine_combo = ttk.Combobox(top_frame,
                                         values=["1. Google(무료)", "2. Papago", "3. ChatGPT", "4. 나만의 로컬 NLLB",
                                                 "5. Gemini(추천)"], width=18, state="readonly")
        self.engine_combo.current(4)  # 기본값 Gemini
        self.engine_combo.grid(row=1, column=1, padx=5, pady=5, sticky='w')

        # 언어 선택 드롭다운 매핑
        lang_list = [f"{v[0]} ({k})" for k, v in LANG_MENU.items()]

        ttk.Label(top_frame, text="출발 언어:").grid(row=1, column=2, padx=5, pady=5, sticky='e')
        self.src_combo = ttk.Combobox(top_frame, values=lang_list, width=15, state="readonly")
        self.src_combo.set("영어 (2)")  # 기본값 영어
        self.src_combo.grid(row=1, column=3, padx=5, pady=5, sticky='w')

        ttk.Label(top_frame, text="도착 언어:").grid(row=2, column=2, padx=5, pady=5, sticky='e')
        self.dest_combo = ttk.Combobox(top_frame, values=lang_list, width=15, state="readonly")
        self.dest_combo.set("한국어 (1)")  # 기본값 한국어
        self.dest_combo.grid(row=2, column=3, padx=5, pady=5, sticky='w')

        # 옵션 체크박스
        self.skip_chapters_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top_frame, text="퀘스트 챕터명 및 그룹 번역 제외 (추천)", variable=self.skip_chapters_var).grid(row=2,
                                                                                                         column=0,
                                                                                                         columnspan=2,
                                                                                                         padx=5, pady=5,
                                                                                                         sticky='w')

        # 중간 영역: 모드팩 스크롤 리스트 카드형 배치
        list_label_frame = ttk.Frame(self.root, padding=5)
        list_label_frame.pack(fill=tk.X, padx=10)
        ttk.Label(list_label_frame, text="번역할 대상 모드팩 선택", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(list_label_frame, text="새로고침 🔄", command=self.refresh_modpacks).pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(self.root, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw"))
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 하단 제어 및 게이지 바 영역
        bottom_frame = ttk.Frame(self.root, padding=10)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # 듀얼 프로그레스 바 (전체 진행률 / 현재 파일 내 배치 진행률)
        ttk.Label(bottom_frame, text="전체 모드 자원 번역률:").grid(row=0, column=0, padx=5, sticky='e')
        self.total_progress = ttk.Progressbar(bottom_frame, orient="horizontal", length=600, mode="determinate")
        self.total_progress.grid(row=0, column=1, padx=5, pady=5, sticky='we')
        self.total_label = ttk.Label(bottom_frame, text="0 / 0")
        self.total_label.grid(row=0, column=2, padx=5, sticky='w')

        ttk.Label(bottom_frame, text="현재 파일 번역 진행률:").grid(row=1, column=0, padx=5, sticky='e')
        self.file_progress = ttk.Progressbar(bottom_frame, orient="horizontal", length=600, mode="determinate")
        self.file_progress.grid(row=1, column=1, padx=5, pady=5, sticky='we')
        self.file_label = ttk.Label(bottom_frame, text="0%")
        self.file_label.grid(row=1, column=2, padx=5, sticky='w')

        # 번역 실행 버튼
        self.btn_start = ttk.Button(bottom_frame, text="🚀 초고속 번역 시작", command=self.start_translation_thread)
        self.btn_start.grid(row=0, column=3, rowspan=2, padx=15, pady=5, sticky='nswe')

        # 최하단 콘솔 스타일 로그 터미널 창 부착
        ttk.Label(self.root, text="실시간 번역 콘솔 로그 (CLI 동기화)", style='Header.TLabel').pack(anchor='w', padx=10)
        self.terminal_log = scrolledtext.ScrolledText(self.root, height=12, bg="black", fg="lightgreen",
                                                      font=('Consolas', 9))
        self.terminal_log.pack(fill=tk.X, padx=10, pady=5, side=tk.BOTTOM)

        # sys.stdout을 GUI 내부 터미널 스크롤 창으로 리다이렉트
        sys.stdout = TextRedirector(self.terminal_log)

    def refresh_modpacks(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        active_launcher_paths = load_or_setup_launcher_paths()
        self.modpacks = find_modpacks_deep(active_launcher_paths)

        if not self.modpacks:
            ttk.Label(self.scrollable_frame, text="탐색된 마인크래프트 모드팩 인스턴스가 없습니다.", foreground="red").pack(pady=20)
            return

        for idx, pack in enumerate(self.modpacks):
            card = ttk.Frame(self.scrollable_frame, style='Card.TFrame', padding=8)
            card.pack(fill=tk.X, padx=5, pady=4, expand=True)

            img_icon = self.get_pack_icon(pack['root_path'])
            img_label = ttk.Label(card, image=img_icon)
            img_label.image = img_icon
            img_label.pack(side=tk.LEFT, padx=5)

            info_text = f"[{pack['launcher']}] {pack['name']}\n경로: {pack['root_path']}"
            lbl_info = ttk.Label(card, text=info_text, justify=tk.LEFT, background='#E8F5E9')
            lbl_info.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

            btn_select = ttk.Button(card, text="선택 🎯", command=lambda p=pack, c=card: self.select_pack(p, c))
            btn_select.pack(side=tk.RIGHT, padx=5)

    def get_pack_icon(self, root_path):
        possible_paths = [
            os.path.join(root_path, "instance.png"),
            os.path.join(os.path.dirname(root_path), "instance.png"),
            os.path.join(root_path, "icon.png")
        ]
        for p in possible_paths:
            if os.path.exists(p):
                try:
                    img = Image.open(p).resize((40, 40), Image.Resampling.LANCZOS)
                    return ImageTk.PhotoImage(img)
                except Exception:
                    pass
        dummy_img = Image.new('RGB', (40, 40), color='#4A3B2C')
        return ImageTk.PhotoImage(dummy_img)

    def select_pack(self, pack, clicked_card):
        self.selected_pack = pack
        for child in self.scrollable_frame.winfo_children():
            child.configure(style='Card.TFrame')
        clicked_card.configure(style='TFrame')
        print(f"🎯 대상 모드팩 선택 완료: {pack['name']}")

    def start_translation_thread(self):
        if not self.selected_pack:
            messagebox.showwarning("경고", "번역할 모드팩 카드를 먼저 선택해 주세요!")
            return
        t = threading.Thread(target=self.run_translation_core, daemon=True)
        t.start()

    # =====================================================================
    # 3. 비동기식 백그라운드 번역 메인 엔진 코어
    # =====================================================================
    def run_translation_core(self):
        self.btn_start.config(state=tk.DISABLED)
        output_folder = "output"
        temp_build_folder = "temp_build"

        os.makedirs(output_folder, exist_ok=True)
        if os.path.exists(temp_build_folder):
            shutil.rmtree(temp_build_folder)
        os.makedirs(temp_build_folder, exist_ok=True)

        choice = str(self.engine_combo.current() + 1)
        src_raw = self.src_combo.get()
        dest_raw = self.dest_combo.get()
        src_lang = re.search(r'\((.*?)\)', src_raw).group(1)
        dest_lang = re.search(r'\((.*?)\)', dest_raw).group(1)
        final_lang_code = get_final_lang_code(dest_lang)
        skip_chapters = self.skip_chapters_var.get()

        print("\n============================================================")
        print(f" 🚀 GUI 연동 멀티 엔진 번역 세션 가동 시작")
        print(f" 엔진 코드: {choice} | 원본: {src_lang} -> 타겟: {final_lang_code}")
        print("============================================================")

        translator, max_batch_chars = get_translator(choice, src_lang, dest_lang)
        if not translator:
            print("[오류] 번역기 엔진 인스턴스를 빌드하지 못했습니다.")
            self.btn_start.config(state=tk.NORMAL)
            return

        tasks_to_run = parse_target_localization_files(
            self.selected_pack['config_path'], self.selected_pack['root_path'], src_lang, final_lang_code
        )

        if not tasks_to_run:
            print("\n[안내] 처리 대상 순수 언어 파일 구조를 찾지 못해 종료합니다.")
            self.btn_start.config(state=tk.NORMAL)
            return

        total_files = len(tasks_to_run)
        print(f"\n총 {total_files}개의 자원을 순차 처리합니다.")

        self.total_progress['maximum'] = total_files

        for f_idx, task in enumerate(tasks_to_run):
            self.total_progress['value'] = f_idx + 1
            self.total_label.config(text=f"{f_idx + 1} / {total_files} 파일 진행 중")
            self.root.update_idletasks()

            content, matches, skip_map = extract_strings_from_file(task['input_path'], skip_chapters)
            unique_matches = [t for t in set(matches) if not (skip_chapters and t in skip_map)]

            target_out_path = os.path.join(temp_build_folder, task['output_rel_path'])

            if not task['is_quest']:
                dir_name = os.path.dirname(target_out_path)
                target_out_path = os.path.join(dir_name, f"{final_lang_code}{task['ext']}")

            existing_translations = task.get('existing_translations', {})
            if existing_translations:
                unique_matches = [m for m in unique_matches if m not in existing_translations]

            if not unique_matches:
                print(f"[{task['display_name']}] 기번역 자동 스킵 완료.")
                save_translated_file(target_out_path, content, existing_translations, task['ext'])
                continue

            chunks = build_batches(unique_matches, max_batch_chars, encode_text)
            total_chunks = len(chunks)

            self.file_progress['maximum'] = total_chunks
            translated_map = dict(existing_translations)

            for text in matches:
                if not text.strip() or text.startswith('{@') or (skip_chapters and text in skip_map):
                    translated_map[text] = text

            for idx, chunk in enumerate(chunks):
                batch_result = translate_batch(chunk, translator, decode_text)
                translated_map.update(batch_result)

                self.file_progress['value'] = idx + 1
                percent = (idx + 1) / total_chunks * 100
                self.file_label.config(text=f"{percent:.1f}% ({idx + 1}/{total_chunks})")
                self.root.update_idletasks()

            save_translated_file(target_out_path, content, translated_map, task['ext'])

        # 최종 압축 배포 팩 빌드
        clean_pack_name = re.sub(r'[\/:*?"<>| ]', '_', self.selected_pack['name'])
        date_str = datetime.now().strftime("%m%d")
        zip_filename = f"{clean_pack_name}_{date_str}_{final_lang_code}.zip"
        final_zip_path = os.path.join(output_folder, zip_filename)

        with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_build_folder):
                for file in files:
                    full_p = os.path.join(root, file)
                    zipf.write(full_p, os.path.relpath(full_p, temp_build_folder))

        shutil.rmtree(temp_build_folder)
        print(f"\n🎉 번역 완료 패키지 생성 배포 완료! -> {final_zip_path}")
        messagebox.showinfo("완료", f"모드팩 번역 배포 파일 생성이 성공적으로 끝났습니다!\n결과물: {final_zip_path}")
        self.btn_start.config(state=tk.NORMAL)


# =====================================================================
# 4. 순수 GUI 창 실행 진입점
# =====================================================================
if __name__ == "__main__":
    main_window = tk.Tk()
    app = TranslatorGUI(main_window)
    main_window.mainloop()
