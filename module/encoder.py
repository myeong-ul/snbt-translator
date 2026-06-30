# module/encoder.py
import json
import os
import re

GLOSSARY_FILE = "glossary.json"


def load_glossary():
    """glossary.json 파일을 읽어옵니다."""
    if os.path.exists(GLOSSARY_FILE):
        try:
            with open(GLOSSARY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_glossary(glossary):
    """용어집에 새 단어가 추가되면 저장합니다."""
    with open(GLOSSARY_FILE, 'w', encoding='utf-8') as f:
        json.dump(glossary, f, ensure_ascii=False, indent=4)


def encode_text(text):
    """실시간 glossary.json 기반으로 고유명사와 색상 코드를 태그로 인코딩합니다."""
    # 1. 색상 코드 인코딩 (&c -> [#c])
    color_pattern = re.compile(r'&([a-zA-F0-9klmnoorKLMNOOR])')
    text = color_pattern.sub(r'[#\1]', text)

    # 2. 동적 용어집 로드 후 인코딩 (긴 단어 우선)
    glossary = load_glossary()
    if glossary:
        sorted_nouns = sorted(glossary.keys(), key=len, reverse=True)
        for idx, noun in enumerate(sorted_nouns):
            # 단어 경계(\b) 보호
            noun_pattern = re.compile(rf'\b{re.escape(noun)}\b', re.IGNORECASE)
            text = noun_pattern.sub(f'___NOUN_{idx}___', text)

    return text


def decode_text(text):
    """태그들을 동적 용어집에 등록된 한글 번역명으로 치환 복원합니다."""
    # 1. 동적 용어집 기반 복원
    glossary = load_glossary()
    if glossary:
        sorted_nouns = sorted(glossary.keys(), key=len, reverse=True)
        for idx, noun in enumerate(sorted_nouns):
            noun_pattern = re.compile(rf'___\s*NOUN_{idx}\s*___')
            text = noun_pattern.sub(glossary[noun], text)

    # 2. 색상 코드 복원
    color_pattern = re.compile(r'\[\s*#\s*([a-zA-F0-9klmnoorKLMNOOR])\s*\]')
    text = color_pattern.sub(r'&\1', text)

    return text