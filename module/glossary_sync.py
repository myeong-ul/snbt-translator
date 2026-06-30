# module/glossary_sync.py
import json
import os
import re

from .encoder import load_glossary, save_glossary


def parse_lang_file(file_path):
    """구버전 .lang 파일(key=value) 구조를 파싱하여 딕셔너리로 반환합니다."""
    data = {}
    if not os.path.exists(file_path):
        return data

    # 주석 및 빈 줄을 제외하고 key=value 매칭
    lang_pattern = re.compile(r'^\s*([^#=\s]+)\s*=\s*(.+)$')
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = lang_pattern.match(line)
            if match:
                data[match.group(1).strip()] = match.group(2).strip()
    return data


def parse_json_lang_file(file_path):
    """신버전 .json 파일 구조를 파싱하여 플랫한 딕셔너리로 반환합니다."""
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return json.load(f)
    except Exception:
        return {}


def scan_and_build_local_glossary():
    """
    .mct_cache 및 config 폴더를 탐색하여 기번역된 자원으로부터
    용어집(glossary.json)을 자동으로 구축합니다.
    """
    print("\n🔍 [로컬 분석] 모드팩 자원 및 캐시 구조 파악 중...")

    glossary = load_glossary()
    initial_count = len(glossary)

    # 탐색할 기준 경로들 (현재 실행 경로 및 상위 경로 포함 방어선)
    search_paths = ['.', '..']

    en_data = {}
    ko_data = {}

    for base_path in search_paths:
        for root, dirs, files in os.walk(base_path):
            # 1. .mct_cache 또는 모드 lang 폴더 탐색
            if '.mct_cache' in root or 'lang' in root.lower() or 'assets' in root.lower():
                for file in files:
                    file_lower = file.lower()
                    full_path = os.path.join(root, file)

                    # 확장자별 수집 (.json 및 .lang 버전 호환)
                    if file_lower in ['en_us.json', 'en_us.lang']:
                        data = parse_json_lang_file(full_path) if file_lower.endswith('.json') else parse_lang_file(
                            full_path)
                        en_data.update(data)
                    elif file_lower in ['ko_kr.json', 'ko_kr.lang']:
                        data = parse_json_lang_file(full_path) if file_lower.endswith('.json') else parse_lang_file(
                            full_path)
                        ko_data.update(data)

    # 2. FTB Quests 통합 언어팩 구조 전용 탐색 (config/ftbquests/quests/lang/)
    ftb_lang_path = os.path.join('config', 'ftbquests', 'quests', 'lang')
    if os.path.exists(ftb_lang_path):
        for file in os.listdir(ftb_lang_path):
            file_lower = file.lower()
            full_path = os.path.join(ftb_lang_path, file)
            if 'en_us' in file_lower and file_lower.endswith('.json'):
                en_data.update(parse_json_lang_file(full_path))
            elif 'ko_kr' in file_lower and file_lower.endswith('.json'):
                ko_data.update(parse_json_lang_file(full_path))

    # 3. 매칭 및 용어집 주입 단계
    # 영어 원문과 한국어 번역본의 키가 일치하고, 번역된 내용이 원문과 다를 때만 기번역으로 인정
    added_count = 0
    for key, en_val in en_data.items():
        if key in ko_data:
            ko_val = ko_data[key]

            # 의미 없는 빈 칸이거나 원문과 완전히 똑같은 경우는 제외 (실제 번역본만 채택)
            if ko_val.strip() and en_val.strip() and ko_val != en_val:
                # 퀘스트 가독성을 위해 아이템 이름이나 명사 위주로 매칭 (너무 긴 문장 제외 방어선)
                if len(en_val) < 40 and en_val not in glossary:
                    # 마인크래프트 포맷 기호 제거 후 순수 명사만 추출
                    clean_en = re.sub(r'§[0-9a-fk-orA-FK-OR]', '', en_val).strip()
                    clean_ko = re.sub(r'§[0-9a-fk-orA-FK-OR]', '', ko_val).strip()

                    if clean_en and clean_ko and clean_en != clean_ko:
                        glossary[clean_en] = clean_ko
                        added_count += 1

    if added_count > 0:
        save_glossary(glossary)
        print(f"✅ [분석 완료] 기존 캐시 및 FTB lang 구조에서 총 {added_count}개의 고유 기번역 용어를 확보했습니다! (총 용어: {len(glossary)}개)")
    else:
        print(f"ℹ️ [분석 완료] 추가로 가져올 새로운 로컬 기번역 용어가 없습니다. (현재 용어: {initial_count}개)")
