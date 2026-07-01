import json
import os
import re
import sys

CONFIG_FILE = "launcher_config.json"
USER_HOME = os.path.expanduser("~")

DEFAULT_LAUNCHER_PATHS = {
    "CurseForge": os.path.join(USER_HOME, "CurseForge", "Minecraft", "Instances"),
    "Prism Launcher": os.path.join(USER_HOME, "AppData", "Roaming", "PrismLauncher",
                                   "instances") if os.name == 'nt' else os.path.join(USER_HOME, ".local", "share",
                                                                                     "PrismLauncher", "instances"),
    "Modrinth App": os.path.join(USER_HOME, "AppData", "Roaming", "ModrinthApp",
                                 "profiles") if os.name == 'nt' else os.path.join(USER_HOME, ".local", "share",
                                                                                  "ModrinthApp", "profiles")
}

LANG_MENU = {
    "1": ("한국어", "ko"), "2": ("영어", "en"), "3": ("일본어", "ja"),
    "4": ("중국어 (간체)", "zh-cn"), "5": ("중국어 (번체)", "zh-tw"),
    "6": ("러시아어", "ru"), "7": ("독일어", "de"), "8": ("프랑스어", "fr"),
    "9": ("스페인어", "es"), "10": ("포르투갈어", "pt"), "11": ("이탈리아어", "it"),
    "12": ("베트남어", "vi"), "13": ("태국어", "th"), "14": ("인도네시아어", "id"),
    "15": ("터키어", "tr")
}

MC_FULL_CODE_MAP = {
    "ko": "ko_kr", "en": "en_us", "ja": "ja_jp", "zh": "zh_cn",
    "zh-cn": "zh_cn", "zh-tw": "zh_tw", "ru": "ru_ru", "de": "de_de",
    "fr": "fr_fr", "es": "es_es", "pt": "pt_pt", "it": "it_it",
    "vi": "vi_vn", "th": "th_th", "id": "id_id", "tr": "tr_tr"
}

# 대소문자 구분 없이 매칭하도록 플래그 수정
LANG_FILE_PATTERN = re.compile(r'^[a-zA-Z]{2,3}(_|-)[a-zA-Z]{2,4}\.json$', re.IGNORECASE)


def print_progress_bar(current, total, display_name, bar_length=30):
    percent = float(current) * 100 / total if total > 0 else 100
    arrow = '■' * int(percent / 100 * bar_length)
    spaces = '□' * (bar_length - len(arrow))
    sys.stdout.write(f"\r[{display_name}] 진행률: [{arrow}{spaces}] {percent:.1f}% ({current}/{total} 묶음 완료)")
    sys.stdout.flush()


def select_language(prompt_msg, default_code):
    print(f"\n[ {prompt_msg} ]")
    print("-" * 50)
    menu_items = list(LANG_MENU.items())
    for i in range(0, len(menu_items), 3):
        row_str = ""
        for j in range(3):
            if i + j < len(menu_items):
                num, (name, code) = menu_items[i + j]
                row_str += f"{num:><2}. {name}({code})".ljust(18)
        print(row_str)
    print("16. 직접 언어 코드 입력하기")
    print("-" * 50)

    choice = input(f"➔ 선택 (기본값번호/코드 입력 가능, 기본 {default_code}): ").strip().lower()
    if not choice: return default_code
    if choice in LANG_MENU: return LANG_MENU[choice][1]
    if choice == "16":
        direct_code = input("➔ 언어 코드를 직접 입력하세요 (예: fr_fr): ").strip().lower()
        return direct_code if direct_code else default_code
    return choice.replace("-", "_")


def get_final_lang_code(dest_lang):
    target_code = dest_lang.lower().replace("-", "_")
    return MC_FULL_CODE_MAP.get(target_code, target_code)


def load_or_setup_launcher_paths():
    config_paths = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    config_paths = loaded
        except Exception:
            config_paths = {}

    updated = False
    final_paths = {}

    print("\n🔍 런처 디렉터리 동기화 및 경로 파악 중...")
    print("-" * 60)

    for name, default_path in DEFAULT_LAUNCHER_PATHS.items():
        if name in config_paths and config_paths[name] and os.path.exists(config_paths[name]):
            final_paths[name] = config_paths[name]
            print(f"[설정 로드] {name} 사용자 정의 경로 연결: {final_paths[name]}")
            continue

        if os.path.exists(default_path):
            final_paths[name] = default_path
            print(f"[자동 감지] {name} 기본 디렉터리 식별: {final_paths[name]}")
            continue

    return final_paths


def find_modpacks_deep(launcher_paths):
    modpack_list = []
    for name, base_path in launcher_paths.items():
        if not os.path.exists(base_path):
            continue

        print(f"📂 [{name}] 인스턴스 스캔 시작: {base_path}")
        try:
            for folder in os.listdir(base_path):
                pack_root_candidate = os.path.join(base_path, folder)
                if not os.path.isdir(pack_root_candidate):
                    continue

                prism_config_path = os.path.join(pack_root_candidate, "minecraft", "config")
                standard_config_path = os.path.join(pack_root_candidate, "config")
                dot_mc_config_path = os.path.join(pack_root_candidate, ".minecraft", "config")

                actual_config = None
                actual_root = None

                if os.path.exists(prism_config_path):
                    actual_config = prism_config_path
                    actual_root = os.path.join(pack_root_candidate, "minecraft")
                elif os.path.exists(standard_config_path):
                    actual_config = standard_config_path
                    actual_root = pack_root_candidate
                elif os.path.exists(dot_mc_config_path):
                    actual_config = dot_mc_config_path
                    actual_root = os.path.join(pack_root_candidate, ".minecraft")

                if actual_config and actual_root:
                    if not any(p['root_path'] == actual_root for p in modpack_list):
                        modpack_list.append({
                            "launcher": name, "name": folder, "root_path": actual_root, "config_path": actual_config
                        })
        except Exception as e:
            print(f"[경고] {name} 스캔 중 오류: {e}")
    return modpack_list


def parse_target_localization_files(config_path, root_path, src_lang, final_lang_code):
    """FTB Skies 2 등 대형 모드팩 구조에 맞춰 탐색 영역 및 필터를 대폭 강화한 추적 엔진"""
    tasks = []

    # config 뿐만 아니라 모드팩 최상위 폴더(root_path) 전체를 대상으로 정밀 수집을 진행합니다.
    search_base = root_path if os.path.exists(root_path) else config_path
    print(f"➔ 🔍 번역 대상 리소스 정밀 분석 중 (기반 경로: {search_base})...")

    for root, dirs, files in os.walk(search_base):
        root_lower = root.lower()

        # 임시 빌드나 출력 폴더는 탐색에서 무조건 제외
        if "temp_build" in root_lower or "output" in root_lower:
            continue

        # 1. FTB Quests 구조 식별 강화
        if "ftbquests" in root_lower or "quests" in root_lower:
            for file in files:
                file_ext_lower = os.path.splitext(file)[1].lower()
                # 퀘스트 데이터용 파일들 전부 확보
                if file_ext_lower in ['.snbt', '.json']:
                    full_input_path = os.path.join(root, file)
                    rel_path_from_mc = os.path.relpath(full_input_path, root_path)
                    tasks.append({
                        'input_path': full_input_path, 'output_rel_path': rel_path_from_mc,
                        'display_name': f"Quests/{os.path.basename(file)}", 'ext': file_ext_lower, 'is_quest': True
                    })
            continue

        # 2. 다국어 자원 폴더 (.json 언어 코드 형태 매핑 - 대소문자 무시 보완)
        for file in files:
            file_lower = file.lower()
            if file_lower.endswith('.json') and LANG_FILE_PATTERN.match(file_lower):
                full_input_path = os.path.join(root, file)
                base_name_no_ext = os.path.splitext(file_lower)[0]

                # 원본 언어가 en_us 혹은 en이거나 파일명 자체에 언어 코드가 매칭될 때
                if base_name_no_ext in [src_lang.lower(), "en_us", "en_kr"]:
                    rel_path_from_mc = os.path.relpath(full_input_path, root_path)

                    # 목적지 언어 파일 확인 (ko_kr.json / ko_KR.json 둘 다 대응)
                    target_lang_filename = f"{final_lang_code}.json"
                    pre_translated_file_path = os.path.join(root, target_lang_filename)

                    # 대문자 버전도 추가 검사 (예: ko_KR.json)
                    if not os.path.exists(pre_translated_file_path):
                        alt_filename = f"{final_lang_code.split('_')[0]}_{final_lang_code.split('_')[1].upper()}.json" if '_' in final_lang_code else target_lang_filename
                        alt_path = os.path.join(root, alt_filename)
                        if os.path.exists(alt_path):
                            pre_translated_file_path = alt_path

                    existing_translations = {}
                    if os.path.exists(pre_translated_file_path):
                        try:
                            with open(pre_translated_file_path, 'r', encoding='utf-8') as pf:
                                existing_translations = json.load(pf)
                            print(
                                f"✨ [기번역 자동 연동] '{os.path.basename(root)}/{os.path.basename(pre_translated_file_path)}' 병합 로드 완료.")
                        except Exception:
                            existing_translations = {}

                    tasks.append({
                        'input_path': full_input_path, 'output_rel_path': rel_path_from_mc,
                        'display_name': os.path.relpath(full_input_path,
                                                        config_path) if config_path in full_input_path else rel_path_from_mc,
                        'ext': '.json', 'is_quest': False, 'existing_translations': existing_translations
                    })

    print(f"✅ 필터링 완료: 총 {len(tasks)}개의 유효 번역 자원 파일을 확보했습니다.")
    return tasks
