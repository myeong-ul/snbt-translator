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
