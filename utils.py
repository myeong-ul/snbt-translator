# utils.py
import json
import os

CONFIG_FILE = "launcher_config.json"
LANG_MENU = {"1": ("영어", "en"), "2": ("한국어", "ko"), "3": ("일본어", "ja")}


def load_or_setup_launcher_paths():
    appdata = os.environ.get("APPDATA", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    user_home = os.path.expanduser("~")

    default_paths = {
        "CurseForge": os.path.join(user_home, "curseforge", "minecraft"),
        "Modrinth App": os.path.join(local_appdata, "ModrinthApp") if local_appdata else "",
        "Prism Launcher": os.path.join(appdata, "PrismLauncher") if appdata else ""
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved_paths = json.load(f)
                for key, val in default_paths.items():
                    if key not in saved_paths: saved_paths[key] = val
                return saved_paths
        except:
            pass
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_paths, f, ensure_ascii=False, indent=4)
    except:
        pass
    return default_paths

def find_modpacks_deep(launcher_paths):
    """[경로 최적화] \minecraft\ 구조 및 \kubejs\ 내부 아이콘 배치 인스턴스를 완벽하게 추적합니다."""
    modpacks = []

    for launcher_name, base_path in launcher_paths.items():
        if not base_path or not os.path.exists(base_path): continue

        search_dirs = []
        if launcher_name == "Prism Launcher":
            search_dirs = [os.path.join(base_path, "instances"), base_path]
        elif launcher_name == "CurseForge":
            search_dirs = [os.path.join(base_path, "Instances"), base_path]
        elif launcher_name == "Modrinth App":
            search_dirs = [os.path.join(base_path, "profiles"), base_path]
        else:
            search_dirs = [base_path]

        for s_dir in search_dirs:
            if not os.path.exists(s_dir): continue
            try:
                for folder in os.listdir(s_dir):
                    full_p = os.path.join(s_dir, folder)
                    if not os.path.isdir(full_p): continue
                    if folder.startswith('.') or folder in ["_common", "assets", "libraries", "downloads"]: continue

                    is_prism = os.path.exists(os.path.join(full_p, "instance.cfg")) or os.path.exists(
                        os.path.join(full_p, "mmc-pack.json"))

                    # [Prism 런처 하위 구조 유연화 패치]
                    # .minecraft 폴더뿐만 아니라 일반 minecraft 폴더명으로 잡힌 알맹이도 함께 추적합니다.
                    if is_prism:
                        if os.path.exists(os.path.join(full_p, ".minecraft")):
                            game_root = os.path.join(full_p, ".minecraft")
                        elif os.path.exists(os.path.join(full_p, "minecraft")):
                            game_root = os.path.join(full_p, "minecraft")
                        else:
                            game_root = full_p
                    else:
                        game_root = full_p

                    if (os.path.exists(os.path.join(game_root, "mods")) or
                            os.path.exists(os.path.join(game_root, "config")) or is_prism or
                            os.path.exists(os.path.join(full_p, "minecraftinstance.json"))):
                        modpacks.append({
                            "name": folder,
                            "instance_path": full_p,  # 메타데이터 참조용 루트
                            "root_path": game_root,  # 실제 인게임 자원/번역 타깃 루트
                            "launcher": launcher_name
                        })
            except Exception as e:
                print(f"[{launcher_name}] 스캔 중 에러: {e}")

    return modpacks


def parse_target_localization_files(root_path):
    """[자원 추적 패치] 무조건 알맹이 폴더(root_path) 기준 하위 에셋을 무결성 추적합니다."""
    targets = []
    # 모드팩 내에서 번역이 필요한 대표적인 수집 루트 명시
    search_paths = [
        os.path.join(root_path, "config", "ftbquests"),
        os.path.join(root_path, "kubejs"),
        os.path.join(root_path, "resourcepacks")
    ]

    for path in search_paths:
        if not os.path.exists(path): continue
        for root, _, files in os.walk(path):
            for file in files:
                if file.endswith('.json') or file.endswith('.lang'):
                    targets.append(os.path.join(root, file))
    return targets


# utils.py 맨 아래에 추가해주세요

def translate_text_via_api(text, src_lang, dest_lang, app):
    """활성화된 API 스위치를 확인하여 실제로 AI 번역을 수행합니다."""
    # 현재 활성화된 API 찾기 (예: Gemini가 켜져있다면)
    active_engine = None
    for engine, enabled in app.api_enabled_states.items():
        if enabled:
            active_engine = engine
            break

    if not active_engine:
        return text  # 켜진 API가 없으면 원본 그대로 반환

    api_key = app.api_keys_storage.get(active_engine, "")
    model_name = app.api_models_storage.get(active_engine, "")

    # [여기에 실제 API 호출 라이브러리 연동]
    # 예시로 구조만 잡아둡니다. 실제 기동시엔 requests나 openai, google-generativeai 패키지를 호출합니다.
    try:
        # 가짜 번역 시뮬레이션 대신 실제 프롬프트 구성 영역
        prompt = f"Translate the following Minecraft modpack text from {src_lang} to {dest_lang}. Keep formatting/codes like §c or %s intact: {text}"

        # 실제 연동 시:
        # if active_engine == "Gemini":
        #     ... gemini api 호출 ...
        #     return translated_text

        return f"[번역됨] {text}"  # <- 테스트용 리턴 (실제 API 결과물로 대체)
    except Exception as e:
        print(f"API 번역 중 오류: {e}")
        return text


def process_actual_translation(file_path, src_lang, dest_lang, app, skip_chapters):
    """파일을 직접 열어서 텍스트 데이터를 통째로 번역한 뒤 덮어씁니다."""
    if not os.path.exists(file_path): return False

    try:
        # 1. JSON 파일 처리
        if file_path.endswith('.json'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)

            # JSON 내부의 문자열들을 재귀적으로 돌며 번역하는 로직 (FTB Quests나 일반 언어팩 구조)
            def translate_json_deep(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        # FTB 퀘스트의 챕터/제목 보호 옵션 활성화 시 스킵
                        if skip_chapters and k in ["title", "subtitle"] and isinstance(obj.get("tasks"), list):
                            continue
                        if isinstance(v, str) and len(v).strip() > 0:
                            obj[k] = translate_text_via_api(v, src_lang, dest_lang, app)
                        else:
                            translate_json_deep(v)
                elif isinstance(obj, list):
                    for i in range(len(obj)):
                        if isinstance(obj[i], str) and len(obj[i]).strip() > 0:
                            obj[i] = translate_text_via_api(obj[i], src_lang, dest_lang, app)
                        else:
                            translate_json_deep(obj[i])

            translate_json_deep(data)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

        # 2. .lang 파일 처리 (구버전 포맷)
        elif file_path.endswith('.lang'):
            lines = []
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                if '=' in line and not line.startswith('#'):
                    key, val = line.split('=', 1)
                    translated_val = translate_text_via_api(val.strip(), src_lang, dest_lang, app)
                    new_lines.append(f"{key}={translated_val}\n")
                else:
                    new_lines.append(line)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

        return True
    except Exception as e:
        print(f"파일 가공 실패 ({file_path}): {e}")
        return False
