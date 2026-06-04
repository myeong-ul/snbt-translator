import re

PROPER_NOUNS = [
    "Ad Astra", "Mekanism", "Netherite", "Mithril", "Steel Ingot", "Redstone"
]


def encode_text(text):
    """번역기에 보내기 전 색상 코드와 고유명사를 안전한 태그로 인코딩합니다."""
    # 1. 색상 코드 인코딩 (&c -> [#c])
    color_pattern = re.compile(r'&([a-zA-F0-9klmnoorKLMNOOR])')
    text = color_pattern.sub(r'[#\1]', text)

    # 2. 고유명사 인코딩 (Mekanism -> ___NOUN_1___)
    sorted_nouns = sorted(PROPER_NOUNS, key=len, reverse=True)
    for idx, noun in enumerate(sorted_nouns):
        noun_pattern = re.compile(rf'\b{re.escape(noun)}\b', re.IGNORECASE)
        text = noun_pattern.sub(f'___NOUN_{idx}___', text)

    return text


def decode_text(text):
    """번역기에서 돌아온 텍스트의 태그들을 다시 원래의 서식과 명사로 복원합니다."""
    # 1. 고유명사 복원 (공백 깨짐 방어)
    sorted_nouns = sorted(PROPER_NOUNS, key=len, reverse=True)
    for idx, noun in enumerate(sorted_nouns):
        noun_pattern = re.compile(rf'___\s*NOUN_{idx}\s*___')
        text = noun_pattern.sub(noun, text)

    # 2. 색상 코드 복원 (번역기가 넣은 임의의 공백 [ # c ] 완벽 대응)
    color_pattern = re.compile(r'\[\s*#\s*([a-zA-F0-9klmnoorKLMNOOR])\s*\]')
    text = color_pattern.sub(r'&\1', text)

    return text
