import json
import os
import re


def extract_strings_from_file(file_path, skip_chapters=False):
    """
    파일을 읽어 내부에 포함된 모든 따옴표 문자열을 추출합니다.
    챕터 스킵 옵션이 활성화된 경우 특정 패턴의 문자열은 skip_map에 기록합니다.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 기본 따옴표 문자열 추출 정규식
    string_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
    matches = string_pattern.findall(content)

    skip_map = {}
    if skip_chapters:
        # SNBT 구조 스킵 패턴 (filename: "...", group: "...")
        snbt_meta = re.compile(r'(filename|group)\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')
        for m in snbt_meta.finditer(content):
            skip_map[m.group(2)] = True

        # JSON/통합 언어팩 스킵 패턴 (chapter.ID.title: "...")
        lang_meta = re.compile(r'(file|chapter|chapter_group)\.[a-zA-Z0-9_.]+\s*[:=]\s*"([^"\\]*(?:\\.[^"\\]*)*)"')
        for m in lang_meta.finditer(content):
            skip_map[m.group(2)] = True

    return content, matches, skip_map


def save_translated_file(output_path, original_content, translated_map, file_ext):
    """번역된 맵을 바탕으로 원본 문자열을 치환하여 최종 파일을 저장합니다."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    string_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')

    # SNBT나 일반 파일은 정규식 치환 방식으로 처리
    if file_ext in ['.snbt', '.txt']:
        final_content = string_pattern.sub(lambda m: f'"{translated_map.get(m.group(1), m.group(1))}"',
                                           original_content)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(final_content)

    # JSON 파일인 경우 완벽한 JSON 규격을 유지하기 위해 안전하게 내장 로더로 재조립 가능
    elif file_ext == '.json':
        try:
            # 순수 텍스트 치환이 정형화된 JSON 구조를 깨뜨리지 않도록 방어
            final_content = string_pattern.sub(lambda m: f'"{translated_map.get(m.group(1), m.group(1))}"',
                                               original_content)
            # 문법 검증용 로드 후 정렬 저장
            data = json.loads(final_content)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except json.JSONDecodeError:
            # 혹시라도 JSON 포맷이 깨지면 텍스트 백업 레이어로 저장
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
