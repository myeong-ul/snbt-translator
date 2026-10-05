import os
import re
import sys
import json
import threading
import time
from collections import deque

import requests
from deep_translator import GoogleTranslator, PapagoTranslator, ChatGptTranslator
from dotenv import set_key

from module.encoder import load_glossary, save_glossary
from module.glossary_sync import COMMON_ESSENTIAL_GLOSSARY, DYNAMIC_ITEM_GLOSSARY
from module.nllb_runtime import DEFAULT_ENDPOINT, ensure_nllb_endpoint, normalize_endpoint

# ➔ 🚨 반드시 이 위치에 아래 구분자 변수가 선언되어 있어야 합니다!
DELIMITER = "\n[=]\n"
ENV_FILE = "api.env"
TRANSLATION_CACHE_FILE = "translation_cache.json"
GOOGLE_REQUESTS_PER_SECOND = 4
GOOGLE_WINDOW_SECONDS = 1.0
GOOGLE_MAX_RETRIES = 4

_TRANSLATION_CACHE_LOCK = threading.Lock()
_TRANSLATION_CACHE = None

_BAD_TRANSLATIONS = {
    "심판": "심층암",
    "딮슬레이트": "심층암",
    "딥슬레이트": "심층암",
    "깊은 슬레이트": "심층암",
    "심해판": "심층암",
    "갈탄 석탄": "갈탄",
    "조약돌 심층암": "심층암 조약돌",
    "자갈 심층암": "심층암 조약돌",
}


def _load_translation_cache():
    global _TRANSLATION_CACHE
    if _TRANSLATION_CACHE is not None:
        return _TRANSLATION_CACHE
    try:
        with open(TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        _TRANSLATION_CACHE = data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        _TRANSLATION_CACHE = {}
    return _TRANSLATION_CACHE


def _save_translation_cache(cache):
    temp_path = f"{TRANSLATION_CACHE_FILE}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, TRANSLATION_CACHE_FILE)


def _cache_translations(mapping):
    global _TRANSLATION_CACHE
    with _TRANSLATION_CACHE_LOCK:
        cache = _load_translation_cache()
        changed = False
        for source, translated in mapping.items():
            if source != translated and cache.get(source) != translated:
                cache[source] = translated
                changed = True
        if changed:
            _save_translation_cache(cache)
        # 테스트 시 경로를 교체하는 경우에도 현재 로드한 동일 객체를 명시적으로 유지한다.
        _TRANSLATION_CACHE = cache
        return cache


def _is_rate_limit_error(error):
    text = str(error).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


class GoogleRequestQueue:
    """최근 1초 동안 API 요청을 최대 N개만 허용하는 FIFO 슬라이딩 윈도우 큐."""

    def __init__(self, requests_per_second: int, window_seconds: float = 1.0):
        self.limit = max(1, requests_per_second)
        self.window = max(0.1, window_seconds)
        self._condition = threading.Condition()
        self._timestamps = deque()
        self._waiting = 0

    def acquire(self, cancel_event=None, log_func=None) -> float:
        """요청 순번을 예약하고 실제 API 호출 직전까지 대기한다."""
        waited = 0.0
        started_at = time.monotonic()
        with self._condition:
            self._waiting += 1
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("번역 중지 요청")
                    now = time.monotonic()
                    while self._timestamps and self._timestamps[0] <= now - self.window:
                        self._timestamps.popleft()
                    if len(self._timestamps) < self.limit:
                        self._timestamps.append(now)
                        waited = now - started_at
                        if waited >= 0.01 and log_func:
                            log_func(
                                f"[API 큐] Google 요청 승인, {waited:.2f}초 대기 "
                                f"(최근 {self.window:g}초 제한 {self.limit}회)"
                            )
                        return waited
                    wake_at = self._timestamps[0] + self.window - now
                    self._condition.wait(timeout=max(0.01, wake_at))
            finally:
                self._waiting -= 1
                self._condition.notify_all()

    def reservation_failed(self):
        """실제 호출 전 예약이 무효가 되면 슬롯을 즉시 반환한다."""
        with self._condition:
            if self._timestamps:
                self._timestamps.pop()
            self._condition.notify_all()


_GOOGLE_REQUEST_QUEUE = GoogleRequestQueue(GOOGLE_REQUESTS_PER_SECOND, GOOGLE_WINDOW_SECONDS)


def _wait_interruptibly(seconds, cancel_event=None):
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("번역 중지 요청")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.1))


def _glossary_sort_key(item):
    """숫자 접미사가 있는 전체 키(X1/X2)를 어간보다 먼저 적용한다."""
    source = item[0]
    numeric_suffix = bool(re.search(r"\d+$", source))
    return (numeric_suffix, len(source), source.lower())

try:
    import google.generativeai as genai
except ImportError:
    genai = None


class LocalNLLBTranslator:
    def __init__(self, endpoint=DEFAULT_ENDPOINT):
        self.src_lang = "en"
        self.dst_lang = "ko"
        self.endpoint = normalize_endpoint(endpoint)
        self.lang_map = {"en": "eng_Latn", "ko": "kor_Hang", "ja": "jpn_Jpan", "zh-cn": "zho_Hans",
                         "zh-tw": "zho_Hant"}

    def translate(self, text, src_lang="en", dest_lang="ko"):
        # 들어오는 인자 순서 방어 코드
        src = self.lang_map.get(src_lang.lower(), src_lang) if isinstance(src_lang, str) else "eng_Latn"
        tgt = self.lang_map.get(dest_lang.lower(), dest_lang) if isinstance(dest_lang, str) else "kor_Hang"

        payload = {
            "text": text,  # 무식하게 한줄씩 안보내고 \n[=]\n 으로 묶인 거대한 덩어리를 통째로 한 번에 보냄
            "src_lang": src,
            "tgt_lang": tgt
        }
        try:
            response = requests.post(self.endpoint, json=payload, timeout=180)
            if response.status_code == 200:
                data = response.json()
                if "translated_text" not in data:
                    raise ValueError("NLLB 응답에 translated_text가 없습니다.")
                return data["translated_text"]
            raise RuntimeError(f"NLLB HTTP {response.status_code}: {response.text[:500]}")
        except requests.RequestException as exc:
            raise RuntimeError(f"NLLB 서버 통신 실패 ({self.endpoint}): {exc}") from exc


class OpenAICompatibleTranslator:
    def __init__(self, base_url, api_key="", model_name="", provider="API"):
        self.base_url, self.api_key, self.model_name, self.provider = base_url.rstrip("/"), api_key, model_name, provider
    def translate(self, text, src_lang="en", dest_lang="ko"):
        headers={"Content-Type":"application/json"}
        if self.api_key: headers["Authorization"]=f"Bearer {self.api_key}"
        prompt=f"Translate from {src_lang} to {dest_lang}. Preserve JSON/SNBT structure and each {DELIMITER!r} separator. Return only translated text.\n\n{text}"
        r=requests.post(f"{self.base_url}/chat/completions",headers=headers,json={"model":self.model_name,"messages":[{"role":"user","content":prompt}],"temperature":0.1},timeout=180)
        if r.status_code>=400: raise RuntimeError(f"{self.provider} HTTP {r.status_code}: {r.text[:500]}")
        return r.json()["choices"][0]["message"]["content"].strip()

class OllamaTranslator(OpenAICompatibleTranslator):
    def __init__(self): super().__init__(os.getenv("OLLAMA_ENDPOINT","http://127.0.0.1:11434/v1"),"",os.getenv("OLLAMA_MODEL","llama3.1:8b"),"Ollama")

class OpenRouterTranslator(OpenAICompatibleTranslator):
    def __init__(self, api_key="", model_name=""):
        super().__init__(
            os.getenv("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1"),
            api_key or os.getenv("OPENROUTER_API_KEY", ""),
            model_name or os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
            "OpenRouter",
        )

class ClaudeTranslator:
    """Anthropic Claude 공식 API 전용 번역기 (엔드포인트 고정, 입력 불필요)"""

    def __init__(self, api_key="", model_name=""):
        self.api_key = api_key or os.getenv("CLAUDE_API_KEY", "")
        self.model_name = model_name or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.src_lang = "en"
        self.dst_lang = "ko"

    def translate(self, text, src_lang="en", dest_lang="ko"):
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        prompt = (
            f"Translate from {src_lang} to {dest_lang}. "
            f"Preserve JSON/SNBT structure and each {DELIMITER!r} separator. "
            f"Return only translated text.\n\n{text}"
        )
        payload = {
            "model": self.model_name,
            "max_tokens": 8192,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        r = requests.post(self.api_url, headers=headers, json=payload, timeout=180)
        if r.status_code >= 400:
            raise RuntimeError(f"Claude HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "").strip()
        raise RuntimeError("Claude 응답에 텍스트가 없습니다.")

class GeminiTranslator:
    """Gemini API (Google AI Studio) 연동 클래스"""

    def __init__(self, api_key, model_name="gemini-1.5-flash"):
        if not genai:
            print("[오류] Gemini 연동을 위해 'pip install google-generativeai' 가 필요합니다.")
            sys.exit(1)
        genai.configure(api_key=api_key)
        # 게임 퀘스트/언어 파일 번역에 최적화된 프롬프트 시스템 지침 주입
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction="너는 마인크래프트 모드팩 전문 번역가야. 전달받는 텍스트의 JSON/SNBT 포맷 구조나 특수 제어 코드(예: §c, {0})는 절대 건드리지 말고, 오직 내부의 문장과 단어만 자연스러운 문맥으로 번역해줘."
        )

    def translate(self, text, src_lang, dest_lang):
        prompt = f"다음 텍스트를 출발어({src_lang})에서 목적어({dest_lang})로 번역해줘:\n\n{text}"
        try:
            response = self.model.generate_content(prompt)
            if response.text:
                return response.text.strip()
            return text
        except Exception as e:
            return f"[Gemini 에러: {e}] {text}"


def get_translator(
    choice,
    src_lang,
    dest_lang,
    endpoint=None,
    cancel_event=None,
    log_func=None,
    api_key=None,
    model_name=None,
):
    """번역 엔진을 만들고 NLLB는 주소 준비·자동 설치·기동까지 보장한다."""
    log = log_func or print
    # 1~3번은 기존 모듈의 코드 흐름 유지 (생략된 기존 논리 연동)
    if choice == "1":
        return GoogleTranslator(src_lang, dest_lang), 2000
    elif choice == "2":
        return PapagoTranslator(src_lang, dest_lang), 2000
    elif choice == "3":
        return ChatGptTranslator(src_lang, dest_lang), 2000

    # ➔ 4번: 새로 생성한 나만의 고속 로컬 NLLB API 서버 연동
    elif choice == "4":
        endpoint = ensure_nllb_endpoint(
            endpoint,
            auto_install=True,
            auto_start=True,
            cancel_event=cancel_event,
            log_func=log,
        )
        translator_instance = LocalNLLBTranslator(endpoint=endpoint)
        translator_instance.src_lang = src_lang
        translator_instance.dst_lang = dest_lang
    # CPU NLLB는 큰 청크 하나를 180초 안에 끝내기 어렵고, 실패하면 요청 전체를
        # 다시 계산해야 한다. 작은 청크로 나누면 진행 상황을 잃지 않고 증분 결과를 캐시할 수 있다.
        nllb_batch_chars = max(500, min(1800, int(os.getenv("SNBT_NLLB_MAX_CHARS", "1200"))))
        return translator_instance, nllb_batch_chars

    # ➔ 5번: 제미나이(Gemini AI) 공식 API 연동
    elif choice == "5":
        if not api_key:
            api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            api_key = input("➔ Gemini API Key를 입력하세요: ").strip()
        if not api_key:
            print("[오류] API Key가 유효하지 않습니다.")
            return None, 0

        # 가성비와 속도가 좋은 1.5-flash 모델을 기본값으로 타겟팅합니다.
        gemini_model = model_name or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        translator_instance = GeminiTranslator(api_key=api_key, model_name=gemini_model)
        translator_instance.src_lang = src_lang
        translator_instance.dst_lang = dest_lang
        return translator_instance, 2000

    # ➔ 6번: Ollama (로컬) - 엔드포인트/env 고정, 입력 칸 불필요
    elif choice == "6":
        translator_instance = OllamaTranslator()
        translator_instance.src_lang = src_lang
        translator_instance.dst_lang = dest_lang
        return translator_instance, 2000

    # ➔ 7번: OpenRouter - 엔드포인트 고정 (https://openrouter.ai/api/v1)
    elif choice == "7":
        translator_instance = OpenRouterTranslator(api_key=api_key, model_name=model_name)
        translator_instance.src_lang = src_lang
        translator_instance.dst_lang = dest_lang
        return translator_instance, 2000

    # ➔ 8번: Claude (Anthropic 공식 API) - 엔드포인트 고정 (https://api.anthropic.com/v1)
    elif choice == "8":
        translator_instance = ClaudeTranslator(api_key=api_key, model_name=model_name)
        translator_instance.src_lang = src_lang
        translator_instance.dst_lang = dest_lang
        return translator_instance, 2000

    return None, 0


def safe_replace(text, eng_word, ko_word):
    """
    한글과 영문이 뒤섞인 문장에서 영문 고유명사만 안전하게 치환하는 함수.
    \b(단어 경계)를 사용하여 'Coal'이 'Charcoal'이나 'Lignite'를 오염시키지 않도록 방어합니다.
    """
    # 영문 단어 대소문자 구분 없이 문장 내에서 독립된 단어일 때만 치환 패턴 생성
    pattern = re.compile(r'\b' + re.escape(eng_word) + r'\b', re.IGNORECASE)
    # 치환문을 그대로 넘기면 `re.sub`가 `\\1`, `\\g<...>`, 문자열 끝의 `\\`를
    # 정규식 치환식으로 해석한다. 콜백을 사용하면 평문 용어의 백슬래시도 보존된다.
    return pattern.sub(lambda _match: ko_word, text)

def translate_batch(chunk, translator, decoder_func, cancel_event=None, log_func=None):
    """청크 단위 번역, 캐시 재사용, 제한 재시도 및 결과 후처리를 수행한다."""
    if not chunk:
        return {}

    log = log_func or print
    cache = _load_translation_cache()
    originals = [decoder_func(value) for value in chunk]
    missing = [index for index, source in enumerate(originals) if source not in cache]
    if not missing:
        log(f"[번역 캐시] API 호출 없이 {len(originals)}개 문장 재사용")
        return {source: cache[source] for source in originals}

    uncached_chunk = [chunk[index] for index in missing]
    uncached_originals = [originals[index] for index in missing]
    delimiter_candidates = [DELIMITER]
    translated_lines = None
    translator_type = translator.__class__.__name__
    is_google = translator_type == "GoogleTranslator"

    for attempt, delimiter in enumerate(delimiter_candidates):
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("번역 중지 요청")
            combined_text = delimiter.join(uncached_chunk)
            if is_google:
                _GOOGLE_REQUEST_QUEUE.acquire(cancel_event, log)

            try:
                if hasattr(translator, "src_lang") and hasattr(translator, "dst_lang"):
                    translated_combined = translator.translate(
                        combined_text,
                        src_lang=getattr(translator, "src_lang", "en"),
                        dest_lang=getattr(translator, "dst_lang", "ko"),
                    )
                elif hasattr(translator, "translate"):
                    translated_combined = translator.translate(text=combined_text)
                else:
                    raise AttributeError("지원하지 않는 번역기 인터페이스입니다.")
            except Exception:
                if is_google:
                    _GOOGLE_REQUEST_QUEUE.reservation_failed()
                raise
            if not isinstance(translated_combined, str):
                raise TypeError("번역기가 문자열을 반환하지 않았습니다.")
            lines = translated_combined.split(delimiter)
            if len(lines) == len(uncached_chunk):
                translated_lines = lines
                break
            raise ValueError(f"문장 수 불일치: 원본 {len(uncached_chunk)}, 번역 {len(lines)}")
        except InterruptedError:
            raise
        except Exception as error:
            if is_google and _is_rate_limit_error(error):
                # 슬라이딩 윈도우 큐가 이미 초당 4회를 제한하지만, 서버가 추가 제한을
                # 적용하면 Retry-After 부재 시 보수적으로 지수 백오프를 적용한다.
                backoff = min(2 ** (attempt + 1), 16)
                log(f"[API 제한] 429 감지: {backoff}초 후 동일 청크 큐 재시도")
                _wait_interruptibly(backoff, cancel_event)
                continue

            # 전송/서버 오류로 구분자를 바꿔도 해결되지 않는다. 특히 NLLB read timeout을
            # 구분자별로 네 번 재호출하면 첫 추론이 끝날 때까지 다음 계산까지 누적된다.
            # 원격 번역 결과의 불일치만 다른 구분자로 재시도하고, 구조적 포맷 오류는 즉시 실패시킨다.
            if isinstance(error, (requests.RequestException, RuntimeError, TypeError, AttributeError)):
                raise
            raise

    if translated_lines is None:
        raise RuntimeError(f"청크 번역 실패 ({len(uncached_chunk)}개 문장)")

    translated_map = {}
    for source, translated_encoded in zip(uncached_originals, translated_lines):
        translated = decoder_func(translated_encoded.strip())
        for source_term, target_term in COMMON_ESSENTIAL_GLOSSARY.items():
            translated = safe_replace(translated, source_term, target_term)
        for wrong, right in _BAD_TRANSLATIONS.items():
            translated = translated.replace(wrong, right)
        if re.search(r"[a-zA-Z]", translated):
            for source_term, target_term in sorted(DYNAMIC_ITEM_GLOSSARY.items(), key=_glossary_sort_key, reverse=True):
                translated = safe_replace(translated, source_term, target_term)
        translated_map[source] = translated

    latest_cache = _cache_translations(translated_map)
    batch_map = {source: latest_cache.get(source, translated_map.get(source, source)) for source in originals}
    log(f"[테스트 로그] API {len(uncached_originals)}개, 캐시 재사용 {len(originals) - len(uncached_originals)}개")
    return batch_map

def _get_or_prompt_key(key_name, provider_name):
    api_key = os.getenv(key_name)
    if not api_key:
        print(f"\n[안내] {provider_name}가 {ENV_FILE}에 없습니다.")
        api_key = input(f"➔ {provider_name} 입력: ").strip()
        set_key(ENV_FILE, key_name, api_key)
    return api_key


def scan_and_learn_nouns(unique_strings, translator):
    """
    문장들을 훑으며 마인크래프트 고유 아이템/모드 이름 패턴(대문자로 시작하는 연속된 단어)을
    자동으로 추출하고, 번역기에 단독 조회하여 glossary.json에 자동으로 누적 학습시킵니다.
    """
    glossary = load_glossary()
    updated = False

    # 마인크래프트 아이템 명사구 패턴 감지 (예: Steel Ingot, Refined Obsidian, Mekanism)
    # 2글자 이상의 대문자로 시작하는 단어 조각들을 수집
    noun_pattern = re.compile(r'\b[A-Z][a-zA-Z]{1,15}(?:\s+[A-Z][a-zA-Z]{0,15})\b|\b[A-Z][a-zA-Z]{3,15}\b')

    detected_nouns = set()
    for text in unique_strings:
        # 색상 코드나 시스템 명령어 제외하고 순수 명사구 스캔
        clean_text = re.sub(r'&[a-zA-F0-9klmnoorKLMNOOR]', '', text)
        for noun in noun_pattern.findall(clean_text):
            # 너무 짧거나 일반적인 조사성 단어 필터링 방어선
            if noun.lower() in ["the", "and", "for", "with", "from", "this", "that"]:
                continue
            detected_nouns.add(noun)

    # 새로운 고유명사가 발견되었다면 단독 사전 등록 학습 진행
    new_nouns = [n for n in detected_nouns if n not in glossary]
    if new_nouns:
        print(f"➔ [자동 용어집] 새롭게 감지된 고유 용어 {len(new_nouns)}개를 사전 학습 중...")
        for noun in new_nouns:
            try:
                # todo 배치 생성해서 한번에 요청하기
                translated_noun = translator.translate(text=noun).strip()
                # 번역기 이상으로 문장 구분자가 튀었을 때 방어
                if DELIMITER in translated_noun or len(translated_noun) > len(noun) * 3:
                    continue
                glossary[noun] = translated_noun
                updated = True
            except Exception:
                continue

    if updated:
        save_glossary(glossary)
        print("➔ [자동 용어집] glossary.json 갱신 완료!")


def build_batches(unique_strings, max_batch_chars, encoder_func):
    chunks = []
    current_chunk = []
    current_length = 0

    for text in unique_strings:
        if not text.strip() or text.startswith('{@'):
            continue

        encoded = encoder_func(text)
        estimated_len = len(encoded) + len(DELIMITER)

        if current_length + estimated_len > max_batch_chars:
            chunks.append(current_chunk)
            current_chunk = [encoded]
            current_length = len(encoded)
        else:
            current_chunk.append(encoded)
            current_length += estimated_len

    if current_chunk:
        chunks.append(current_chunk)
    return chunks
