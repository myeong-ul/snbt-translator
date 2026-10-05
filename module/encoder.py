# module/encoder.py
import json
import os
import re
import threading

GLOSSARY_FILE = "glossary.json"
GLOSSARY_MAX_SOURCE_CHARS = 64
GLOSSARY_MAX_TARGET_CHARS = 96
GLOSSARY_MAX_WORDS = 4

_ENCODER_CACHE_LOCK = threading.Lock()
_GLOSSARY_CACHE_KEY = None
_GLOSSARY_CACHE = {}
_ENCODED_NOUN_PATTERN = None
_NOUN_PLACEHOLDERS = {}
_LOWER_PLACEHOLDER_MAP = {}
_SORTED_NOUNS = []
_DECODER_PATTERN = None


def load_glossary():
    """glossary.json 파일을 읽어옵니다."""
    if os.path.exists(GLOSSARY_FILE):
        try:
            with open(GLOSSARY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def is_glossary_term(source, translated=None) -> bool:
    """문장/퀘스트 본문 대신 짧고 독립적인 명사구인지 판별한다."""
    if not isinstance(source, str):
        return False
    source = re.sub(r"[&§][0-9a-zA-Z]", "", source).strip()
    if not source or not re.search(r"[A-Za-z]", source):
        return False
    if len(source) > GLOSSARY_MAX_SOURCE_CHARS:
        return False
    words = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", source)
    if not words or len(words) > GLOSSARY_MAX_WORDS:
        return False
    lowered_words = [word.lower() for word in words]
    # 영어 명령문/설명문 시작 동사. 단독 아이템 명사에는 등장하지 않는 표현이다.
    instruction_verbs = {
        "building", "click", "complete", "connect", "craft", "creating",
        "find", "get", "hunting", "increase", "increases", "kill", "make",
        "making", "obtain", "open", "observe", "place", "press", "read",
        "right", "sticking", "use", "using", "wait",
    }
    if lowered_words[0] in instruction_verbs:
        return False
    # 마침표/물음표/느낌표/쉼표/콜론/세미콜론은 정상 명사구보다 문장을 강하게 나타낸다.
    if re.search(r"[.?!,;:]", source) or "\n" in source or "\r" in source:
        return False
    if translated is not None:
        if not isinstance(translated, str):
            return False
        translated = re.sub(r"[&§][0-9a-zA-Z]", "", translated).strip()
        if not translated or len(translated) > GLOSSARY_MAX_TARGET_CHARS:
            return False
        if re.search(r"[.?!,;:]", translated) or "\n" in translated or "\r" in translated:
            return False
    return True


def sanitize_glossary(glossary):
    """저장 전에 문장과 장문 항목을 제거하고 색상 코드 없는 원형으로 정규화한다."""
    if not isinstance(glossary, dict):
        return {}
    clean = {}
    for source, translated in glossary.items():
        normalized_source = re.sub(r"[&§][0-9a-zA-Z]", "", source).strip() if isinstance(source, str) else ""
        normalized_target = re.sub(r"[&§][0-9a-zA-Z]", "", translated).strip() if isinstance(translated, str) else ""
        if is_glossary_term(normalized_source, normalized_target):
            clean[normalized_source] = normalized_target
    return clean


def save_glossary(glossary):
    """문장/장문을 제외한 단어·짧은 명사구만 JSON에 저장한다."""
    clean_glossary = sanitize_glossary(glossary)
    with open(GLOSSARY_FILE, 'w', encoding='utf-8') as f:
        json.dump(clean_glossary, f, ensure_ascii=False, indent=4)
    return clean_glossary


def _glossary_cache_key():
    path = os.path.abspath(GLOSSARY_FILE)
    try:
        stat = os.stat(path)
        return path, stat.st_mtime_ns, stat.st_size
    except OSError:
        return path, None, 0


def _get_cached_glossary():
    """문자열마다 JSON/정규식을 다시 만들지 않고 파일 변경 시에만 무효화한다."""
    global _GLOSSARY_CACHE_KEY, _GLOSSARY_CACHE, _ENCODED_NOUN_PATTERN
    global _NOUN_PLACEHOLDERS, _LOWER_PLACEHOLDER_MAP
    global _SORTED_NOUNS, _DECODER_PATTERN
    key = _glossary_cache_key()
    with _ENCODER_CACHE_LOCK:
        if key == _GLOSSARY_CACHE_KEY:
            return _GLOSSARY_CACHE, _ENCODED_NOUN_PATTERN, _DECODER_PATTERN
        glossary = load_glossary()
        if not isinstance(glossary, dict):
            glossary = {}
        sorted_nouns = sorted(
            (str(noun) for noun in glossary if isinstance(noun, str) and noun),
            key=len,
            reverse=True,
        )
        placeholders = {
            noun: f"___NOUN_{index}___" for index, noun in enumerate(sorted_nouns)
        }
        encoded_pattern = None
        decoder_pattern = None
        if sorted_nouns:
            # 사전이 매우 크므로 각 문장마다 3천 개 패턴을 만들지 않고 한 번만 조합한다.
            noun_alternation = "|".join(re.escape(noun) for noun in sorted_nouns)
            encoded_pattern = re.compile(
                rf"\b(?:{noun_alternation})\b",
                re.IGNORECASE,
            )
            decoder_pattern = re.compile(
                r"___\s*NOUN_(\d+)\s*___",
                re.IGNORECASE,
            )
        _GLOSSARY_CACHE_KEY = key
        _GLOSSARY_CACHE = glossary
        _ENCODED_NOUN_PATTERN = encoded_pattern
        _NOUN_PLACEHOLDERS = placeholders
        _LOWER_PLACEHOLDER_MAP = {
            noun.lower(): placeholder for noun, placeholder in placeholders.items()
        }
        _SORTED_NOUNS = sorted_nouns
        _DECODER_PATTERN = decoder_pattern
        return glossary, encoded_pattern, decoder_pattern


def encode_text(text):
    """실시간 glossary.json 기반 고유명사와 색상 코드를 태그로 인코딩한다."""
    text = re.sub(r"&([a-zA-F0-9klmnoorKLMNOOR])", r"[#\1]", text)
    _, noun_pattern, _ = _get_cached_glossary()
    if noun_pattern is None:
        return text

    # alternation은 대소문자 무시이므로 매칭 문자열을 소문자로 정규화한다.
    return noun_pattern.sub(
        lambda match: _LOWER_PLACEHOLDER_MAP.get(match.group(0).lower(), match.group(0)),
        text,
    )


def decode_text(text):
    """태그들을 동적 용어집에 등록된 한글 번역명으로 치환 복원한다."""
    glossary, _, decoder_pattern = _get_cached_glossary()
    if decoder_pattern is not None:
        def replace_placeholder(match):
            try:
                return str(glossary[_SORTED_NOUNS[int(match.group(1))]])
            except (ValueError, IndexError, KeyError, TypeError):
                return match.group(0)

        text = decoder_pattern.sub(replace_placeholder, text)
    return re.sub(r"\[\s*#\s*([a-zA-F0-9klmnoorKLMNOOR])\s*\]", r"&\1", text)
