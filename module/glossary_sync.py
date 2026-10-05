import json
import os
import re
import urllib.request
from typing import Callable, Iterable, Optional, Tuple

ProgressCallback = Callable[[int, int, str], None]

from .encoder import is_glossary_term, load_glossary, sanitize_glossary, save_glossary


COMMON_ESSENTIAL_GLOSSARY = {
    "Deepslate": "심층암",
    "Cobbled Deepslate": "심층암 조약돌",  # '조약돌 심층암' 꼬임 방지
    "Lignite": "갈탄",
    "Lead Ore": "납 광석",
    "Lead Ingot": "납 주괴",
}

# 번역 결과에 적용되는 실시간 용어집. 값 변경 시 참조가 유지되도록 반드시 갱신한다.
DYNAMIC_ITEM_GLOSSARY = {}

_OFFICIAL_GLOSSARY = {
    "deepslate": "심층암",
    "netherite": "네더라이트",
    "obsidian": "흑요석",
}
_FORCED_CORRECTIONS = {
    "딮슬레이트": "심층암",
    "딥슬레이트": "심층암",
    "심판": "심층암",
}


def _clean_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"§[0-9a-fk-orA-FK-OR]", "", value).strip()


def _valid_glossary_entry(source, translated) -> bool:
    source = _clean_text(source)
    translated = _clean_text(translated)
    return bool(source and translated and source != translated)


def _set_term(glossary: dict, source, translated, *, overwrite: bool = True) -> bool:
    """짧은 단어·명사구만 저장하고 실제 변경 여부를 반환한다."""
    if not _valid_glossary_entry(source, translated) or not is_glossary_term(source, translated):
        return False
    source = _clean_text(source)
    translated = _clean_text(translated)
    if not overwrite and source in glossary:
        return False
    if glossary.get(source) == translated:
        return False
    glossary[source] = translated
    return True


def _official_terms_from_data(official_data: dict) -> dict:
    result = {}
    for key, ko_text in official_data.items():
        if not isinstance(key, str) or not _valid_glossary_entry(key, ko_text):
            continue
        # item.minecraft.iron_ingot, block.minecraft.deepslate 등
        raw_eng = key.rsplit(".", 1)[-1].replace("_", " ").strip()
        if len(raw_eng) <= 1:
            continue
        result[raw_eng] = ko_text
        result[raw_eng.lower()] = ko_text
        result[raw_eng.title()] = ko_text
    return result


def initialize_master_glossary(local_glossary_data=None, existing_glossary=None) -> dict:
    """공식·기존·로컬 사전을 안전하게 병합해 실제 전역 사전에 반영한다.

    로컬 모드팩의 전용 번역은 공식 번역보다 우선한다. X1/X2 같은 서로 다른
    식별자는 줄이거나 정규화하지 않아 어간 충돌을 원천적으로 피한다.
    """
    global DYNAMIC_ITEM_GLOSSARY

    combined = dict(existing_glossary if isinstance(existing_glossary, dict) else {})
    combined.update(_OFFICIAL_GLOSSARY)

    official_lang_url = (
        "https://raw.githubusercontent.com/InventivetalentDev/"
        "minecraft-assets/1.21.1/assets/minecraft/lang/ko_kr.json"
    )
    try:
        print("🌐 마인크래프트 공식 최신 한국어 자원팩 다운로드 중...")
        with urllib.request.urlopen(official_lang_url, timeout=5) as response:
            official_data = json.loads(response.read().decode("utf-8"))
        official_terms = _official_terms_from_data(official_data)
        combined.update(official_terms)
        print(f"✅ 공식 마크 단어 매핑 완료 ({len(official_terms)}개 단어 확보)")
    except Exception as exc:
        print(f"⚠️ 공식 마크 언어팩 다운로드 실패 (인터넷 연결 확인): {exc}")

    if isinstance(local_glossary_data, dict) and local_glossary_data:
        print(f"📂 로컬 모드팩 기번역 데이터 {len(local_glossary_data)}개 추가 통합 중...")
        for source, translated in local_glossary_data.items():
            clean_source = _clean_text(source)
            clean_translated = _clean_text(translated)
            if not _valid_glossary_entry(clean_source, clean_translated):
                continue
            combined[clean_source] = clean_translated
            # 영문 대소문자 대응은 원형/소문자만 등록하고 숫자 접미사는 그대로 둔다.
            if re.search(r"[a-zA-Z]", clean_source):
                combined.setdefault(clean_source.lower(), clean_translated)

    combined.update(_FORCED_CORRECTIONS)
    # 개체 교체 대신 in-place 갱신하여 from-import 참조도 유지한다.
    DYNAMIC_ITEM_GLOSSARY.clear()
    DYNAMIC_ITEM_GLOSSARY.update(combined)
    print(
        "🚀 최종 마스터 용어 사전 빌드 완료! "
        f"총 {len(DYNAMIC_ITEM_GLOSSARY)}개의 용어 적용 가능."
    )
    return DYNAMIC_ITEM_GLOSSARY


def parse_lang_file(file_path) -> dict:
    """구버전 .lang 파일(key=value) 구조를 파싱한다."""
    if not os.path.isfile(file_path):
        return {}

    data = {}
    lang_pattern = re.compile(r"^\s*([^#=\s]+)\s*=\s*(.+)$")
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            for line in file:
                match = lang_pattern.match(line)
                if match:
                    data[match.group(1).strip()] = match.group(2).strip()
    except OSError:
        return {}
    return data


def parse_json_lang_file(file_path) -> dict:
    """신버전 JSON 언어 파일을 평면 dict로 읽는다."""
    if not os.path.isfile(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_lang_resource(file_path: str) -> dict:
    lower_path = file_path.lower()
    if lower_path.endswith(".json"):
        return parse_json_lang_file(file_path)
    if lower_path.endswith(".lang"):
        return parse_lang_file(file_path)
    return {}


def _language_from_filename(filename: str, relative_path: str) -> Optional[str]:
    lower = f"{filename} {relative_path}".lower().replace("-", "_")
    # en_us를 먼저 검사하여 en_gb와 잘못 잡지 않는다.
    if re.search(r"(?:^|[_/\\.-])en(?:_us)?(?:[_/\\.-]|$)", lower):
        return "en_us"
    if re.search(r"(?:^|[_/\\.-])ko(?:_kr)?(?:[_/\\.-]|$)", lower):
        return "ko_kr"
    return None


def _is_relevant_resource(relative_parts: Iterable[str], relative_path: str) -> bool:
    parts = [part.lower() for part in relative_parts]
    path = relative_path.replace("\\", "/").lower()
    relevant_names = {"config", "assets", ".mct_cache", "ftbquests"}
    relevant_tokens = ("lang", "locale", "localization", "translation", "quest")
    return (
        any(part in relevant_names for part in parts)
        or any(token in part for part in parts for token in relevant_tokens)
        or any(token in path for token in ("/lang/", "/locale/"))
    )


def _inventory_root(root: str, progress_callback: Optional[ProgressCallback] = None,
                    cancel_event=None) -> int:
    """탐색 예상량을 위한 1차 패스. 디렉터리와 후보 파일을 하나의 작업 단위로 센다."""
    total = 0
    if not root or not os.path.isdir(root):
        return 0
    for current_root, dirs, filenames in os.walk(root):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("로컬 glossary 탐색이 중지되었습니다.")
        dirs[:] = [directory for directory in dirs if directory not in {"__pycache__", ".git", "logs"}]
        total += 1
        for filename in filenames:
            if not filename.lower().endswith((".json", ".lang")):
                continue
            try:
                relative_path = os.path.relpath(
                    os.path.join(current_root, filename), root
                ).replace("\\", "/")
            except ValueError:
                continue
            if _is_relevant_resource(relative_path.split("/"), relative_path):
                total += 1
        if progress_callback and total % 100 == 0:
            progress_callback(total, total, "inventory")
    if progress_callback:
        progress_callback(total, total, "inventory")
    return total


def _collect_language_files(
    root: str,
    total_units: int = 0,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event=None,
) -> list:
    files = []
    seen = set()
    processed_units = 0
    if not root or not os.path.isdir(root):
        return files

    for current_root, dirs, filenames in os.walk(root):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("로컬 glossary 탐색이 중지되었습니다.")
        # 불필요한 대형/생성 캐시를 제외하되 .mct_cache는 명시적으로 포함한다.
        dirs[:] = [
            directory for directory in dirs
            if directory not in {"__pycache__", ".git", "logs"}
        ]
        for filename in filenames:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("로컬 glossary 탐색이 중지되었습니다.")
            full_path = os.path.abspath(os.path.join(current_root, filename))
            if not full_path.lower().endswith((".json", ".lang")):
                continue
            try:
                relative_path = os.path.relpath(full_path, root).replace("\\", "/")
            except ValueError:
                continue
            relative_parts = relative_path.split("/")
            if not _is_relevant_resource(relative_parts, relative_path):
                continue
            if progress_callback:
                processed_units += 1
                progress_callback(processed_units, total_units, "scanning")
            if full_path in seen or not _parse_lang_resource(full_path):
                continue
            language = _language_from_filename(filename, relative_path)
            if language:
                files.append((full_path, relative_path, language))
                seen.add(full_path)
        if progress_callback and total_units:
            processed_units += 1  # 디렉터리 처리 완료
            progress_callback(min(processed_units, total_units), total_units, "scanning")
    if progress_callback and total_units:
        progress_callback(total_units, total_units, "scanning")
    return files


def _translation_candidates(source_key: str, source_value: str) -> Tuple[str, ...]:
    """ID 키와 사람이 읽는 값에서 대응 후보를 안전하게 만든다."""
    candidates = []
    for value in (source_key, source_value):
        clean = _clean_text(value)
        if not clean:
            continue
        # key.my_quest.1 같은 단순 ID는 사람이 읽는 원문을 우선한다.
        if clean == source_key and (clean.islower() or "_" in clean):
            readable = clean.replace("_", " ").strip()
            if readable:
                candidates.append(readable)
        candidates.append(clean)

    seen = set()
    return tuple(value for value in candidates if value and not (value in seen or seen.add(value)))


def scan_and_build_local_glossary(
    root_path=None,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event=None,
) -> dict:
    """현재 모드팩의 en_us/en_us.json과 ko_kr/ko_kr.json 대응을 수집한다.

    동일한 언어 파일 경로의 서로 다른 base name은 비교하지 않는다. 정확한
    base name 쌍을 먼저 비교하고, 남은 파일은 상대 경로와 key로 보완 매칭한다.
    반환값은 initialize_master_glossary에 바로 전달할 수 있는 dict이다.
    """
    root = os.path.abspath(root_path or os.getcwd())
    print(f"\n🔍 [로컬 분석] 모드팩 루트 {root}의 언어 자원 분석 중...")

    # 앱의 glossary.json 경로를 유지한다. 호출자가 cwd를 바꿔도 프로젝트 파일을 덮지 않는다.
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        glossary = sanitize_glossary(load_glossary())
    except Exception:
        glossary = {}
    initial_count = len(glossary)

    if progress_callback:
        progress_callback(0, 0, "inventory")
    total_units = _inventory_root(root, progress_callback, cancel_event)
    if progress_callback:
        progress_callback(0, total_units, "scanning")
    language_files = _collect_language_files(root, total_units, progress_callback, cancel_event)
    by_language = {"en_us": [], "ko_kr": []}
    for item in language_files:
        by_language[item[2]].append(item)

    pairs = []
    used_ko = set()

    # 1) en_us.json / ko_kr.json처럼 같은 stem을 가진 파일을 최우선 매칭.
    en_by_stem = {os.path.splitext(item[0])[0].lower(): item for item in by_language["en_us"]}
    for ko_item in by_language["ko_kr"]:
        ko_stem = os.path.splitext(ko_item[0])[0].lower()
        en_item = en_by_stem.get(ko_stem)
        if en_item:
            pairs.append((en_item, ko_item))
            used_ko.add(ko_item[0])

    # 2) 나머지는 상대 경로가 같은 namespace/resource 쌍을 우선 매칭.
    en_by_rel = {item[1].replace("\\", "/").lower(): item for item in by_language["en_us"]}
    for ko_item in by_language["ko_kr"]:
        if ko_item[0] in used_ko:
            continue
        relative = ko_item[1].replace("\\", "/").lower()
        directory = os.path.dirname(relative)
        candidates = [
            f"{directory}/en_us.{ko_item[2].split('_')[-1] and os.path.splitext(ko_item[0])[1][1:]}",
            relative.replace("/ko_kr.", "/en_us."),
        ]
        en_item = en_by_rel.get(candidates[0]) or en_by_rel.get(candidates[1])
        if en_item:
            pairs.append((en_item, ko_item))
            used_ko.add(ko_item[0])

    # 3) 정확한 쌍이 없더라도 전체 key 집합이 겹치면 namespace 우선 순위로 대응한다.
    matched_en = {pair[0][0] for pair in pairs}
    remaining_en = [item for item in by_language["en_us"] if item[0] not in matched_en]
    for ko_item in by_language["ko_kr"]:
        if ko_item[0] in used_ko:
            continue
        ko_data = _parse_lang_resource(ko_item[0])
        overlapping = [item for item in remaining_en if any(key in ko_data for key in _parse_lang_resource(item[0]))]
        if overlapping:
            # 가장 많이 겹치는 단일 파일만 사용해 잘못된 namespace 대응을 방지한다.
            en_item = max(overlapping, key=lambda item: sum(key in ko_data for key in _parse_lang_resource(item[0])))
            pairs.append((en_item, ko_item))
            used_ko.add(ko_item[0])
            remaining_en.remove(en_item)

    added_count = 0
    for en_item, ko_item in pairs:
        en_data = _parse_lang_resource(en_item[0])
        ko_data = _parse_lang_resource(ko_item[0])
        for key, source_value in en_data.items():
            translated_value = ko_data.get(key)
            if translated_value is None:
                continue
            for source, translated in zip(
                _translation_candidates(str(key), source_value),
                _translation_candidates(str(key), translated_value),
            ):
                if _set_term(glossary, source, translated):
                    added_count += 1

    if added_count:
        # encoder는 고정 경로를 사용하므로 저장 직전 cwd를 저장 파일 위치로 맞춘다.
        original_cwd = os.getcwd()
        try:
            os.chdir(app_root)
            save_glossary(glossary)
        finally:
            os.chdir(original_cwd)
        print(
            "✅ [분석 완료] config/assets/.mct_cache/FTB Quests에서 "
            f"{added_count}개의 기번역 용어를 확보했습니다! (총 용어: {len(glossary)}개)"
        )
    else:
        print(f"ℹ️ [분석 완료] 새 로컬 기번역 용어가 없습니다. (현재 용어: {initial_count}개)")
    if progress_callback:
        progress_callback(total_units, total_units, "completed")
    return sanitize_glossary(glossary)
