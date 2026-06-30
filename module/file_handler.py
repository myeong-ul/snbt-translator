# module/file_handler.py
import json
import os
import re


def extract_strings_from_file(file_path, skip_chapters=False):
    """
    파일의 확장자와 내부 구조를 분석하여, 시스템 ID나 코드는 제외하고
    실제 유저에게 노출되는 '번역이 필요한 텍스트'만 정밀 추출합니다.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    file_ext = os.path.splitext(file_path)[1].lower()
    valid_matches = []
    skip_map = {}

    # ====================================================
    # 1. FTB Quests (.snbt) 구조 분석 및 필터링
    # ====================================================
    if file_ext == '.snbt':
        # FTB Quests에서 실제 번역이 필요한 핵심 키들 (제목, 설명, 서브타이블 등)
        # 이 키 뒤에 나오는 따옴표 문자열만 번역 대상으로 인정합니다.
        translation_keys = ["title", "description", "subtitle", "icon"]

        # 정규식 설명: key: "value" 또는 key: [ "value1", "value2" ] 패턴 감지
        # group(1) = 키 이름, group(2) = 값 (또는 배열 형태의 값들)
        snbt_pattern = re.compile(r'([a-zA-Z0-9_]+)\s*:\s*(\[?\s*".*?"\s*\]?)', re.DOTALL)
        string_cleaner = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')

        for match in snbt_pattern.finditer(content):
            key = match.group(1)
            value_block = match.group(2)

            # 챕터 파일 자체의 메타데이터(파일명, 그룹ID) 스킵 요청 처리
            if skip_chapters and key in ["filename", "group"]:
                for s in string_cleaner.findall(value_block):
                    skip_map[s] = True
                continue

            # 중요: 번역이 필요한 핵심 키가 아니라면 (예: id, item, block, type 등) 번역 대상에서 제외
            if key in translation_keys:
                # 블록 안에서 실제 문자열만 추출
                for s in string_cleaner.findall(value_block):
                    valid_matches.append(s)

    # ====================================================
    # 2. 일반 모드팩 언어 파일 (.json) 구조 분석 및 필터링
    # ====================================================
    elif file_ext == '.json':
        try:
            data = json.loads(content)

            # JSON은 플랫한 key-value 구조이거나 중첩 구조이므로, 재귀 함수로 텍스트만 탐색
            def walk_json(node, current_key=""):
                if isinstance(node, dict):
                    for k, v in node.items():
                        walk_json(v, f"{current_key}.{k}" if current_key else k)
                elif isinstance(node, list):
                    for item in node:
                        walk_json(item, current_key)
                elif isinstance(node, str):
                    # 축적된 키 정보를 바탕으로 시스템 코드성 키 필터링
                    # .id, .item, .block, .icon, .uuid 등으로 끝나는 키는 번역 대상에서 제외
                    if any(current_key.lower().endswith(suffix) for suffix in [
                        '.id', '.uuid', '.type', '.item', '.block', '.fluid', '.mod', '.registry'
                    ]):
                        return

                    # 챕터 제목 스킵 로직 (chapter.ID.title 등)
                    if skip_chapters and any(p in current_key.lower() for p in ['chapter', 'chapter_group']):
                        skip_map[node] = True
                        return

                    valid_matches.append(node)

            walk_json(data)
        except json.JSONDecodeError:
            # JSON 포맷이 깨진 경우 예외적으로 정규식 백업 레이어 가동
            string_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
            valid_matches = string_pattern.findall(content)

    # 중복 제거 및 공백 문자 필터링
    unique_matches = list(set([m for m in valid_matches if m.strip()]))
    return content, unique_matches, skip_map


def save_translated_file(output_path, original_content, translated_map, file_ext):
    """번역된 맵을 바탕으로 원본에서 '정확히 번역 대상이었던 문자열만' 치환하여 저장합니다."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 텍스트 파일이나 SNBT는 안전하게 정규식 매칭 치환
    if file_ext in ['.snbt', '.txt']:
        string_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
        # translated_map에 매핑이 있는 녀석(번역 대상이었던 것)만 치환하고, 없는 건 원본 유지
        final_content = string_pattern.sub(lambda m: f'"{translated_map.get(m.group(1), m.group(1))}"',
                                           original_content)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(final_content)

    # JSON 파일 재조립
    elif file_ext == '.json':
        try:
            # 원본 JSON 구조를 깨뜨리지 않기 위해 가독성 포맷 치환 후 규격 검증 저장
            string_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
            final_content = string_pattern.sub(lambda m: f'"{translated_map.get(m.group(1), m.group(1))}"',
                                               original_content)
            data = json.loads(final_content)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except json.JSONDecodeError:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(final_content)