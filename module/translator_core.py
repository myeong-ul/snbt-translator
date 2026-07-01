import os
import re
import sys

import requests
from deep_translator import GoogleTranslator, PapagoTranslator, ChatGptTranslator
from dotenv import set_key

from cli_translator import ENV_FILE
from module.encoder import load_glossary, save_glossary

# ➔ 🚨 반드시 이 위치에 아래 구분자 변수가 선언되어 있어야 합니다!
DELIMITER = "\n[=]\n"

ENV_FILE = "api.env"

try:
    import google.generativeai as genai
except ImportError:
    genai = None


class LocalNLLBTranslator:
    def __init__(self, endpoint="http://192.168.0.35:8000/translate"):
        self.endpoint = endpoint
        self.lang_map = {"en": "eng_Latn", "ko": "kor_Latn", "ja": "jpn_Jpan", "zh-cn": "zhne_Hans",
                         "zh-tw": "zho_Hant"}

    def translate(self, text, src_lang="en", dest_lang="ko"):
        # 들어오는 인자 순서 방어 코드
        src = self.lang_map.get(src_lang.lower(), src_lang) if isinstance(src_lang, str) else "eng_Latn"
        tgt = self.lang_map.get(dest_lang.lower(), dest_lang) if isinstance(dest_lang, str) else "kor_Latn"

        payload = {
            "text": text,  # 무식하게 한줄씩 안보내고 \n[=]\n 으로 묶인 거대한 덩어리를 통째로 한 번에 보냄
            "src_lang": src,
            "tgt_lang": tgt
        }
        try:
            response = requests.post(self.endpoint, json=payload, timeout=60)  # 배치 연산 대기시간 60초로 늘림
            if response.status_code == 200:
                return response.json().get("translated_text", text)
            else:
                return f"[NLLB 에러 {response.status_code}] {text}"
        except Exception as e:
            return f"[NLLB 통신 오류: {e}] {text}"


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


def get_translator(choice, src_lang, dest_lang):
    """
    사용자가 선택한 번역기 엔진을 빌드하여 반환합니다.
    - choice: '1'(구글무료), '2'(파파고), '3'(ChatGPT), '4'(로컬NLLB), '5'(Gemini)
    - 반환값: (translator_instance, max_batch_chars)
    """
    # 1~3번은 기존 모듈의 코드 흐름 유지 (생략된 기존 논리 연동)
    if choice == "1":
        return GoogleTranslator(src_lang, dest_lang), 4000
    elif choice == "2":
        return PapagoTranslator(src_lang, dest_lang), 4000
    elif choice == "3":
        return ChatGptTranslator(src_lang, dest_lang), 4000

    # ➔ 4번: 새로 생성한 나만의 고속 로컬 NLLB API 서버 연동
    elif choice == "4":
        endpoint = input("➔ NLLB 서버 주소 입력 (엔터 입력시 http://http://192.168.0.35:8000/translate): ").strip()
        if not endpoint:
            endpoint = "http://http://192.168.0.35:8000/translate"

        translator_instance = LocalNLLBTranslator(endpoint=endpoint)
        # 로컬 서버이므로 글자 수 제한 트래픽 부담이 적어 배치를 넓게 잡을 수 있습니다.
        return translator_instance, 4000

        # ➔ 5번: 제미나이(Gemini AI) 공식 API 연동
    elif choice == "5":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            api_key = input("➔ Gemini API Key를 입력하세요: ").strip()
        if not api_key:
            print("[오류] API Key가 유효하지 않습니다.")
            return None, 0

        # 가성비와 속도가 좋은 1.5-flash 모델을 기본값으로 타겟팅합니다.
        translator_instance = GeminiTranslator(api_key=api_key, model_name="gemini-1.5-flash")
        return translator_instance, 2000

    return None, 0


def translate_batch(chunk, translator, decoder_func):
    """
    chunk 내부의 모든 문장을 하나의 거대한 텍스트로 묶어
    단 1번의 통신(초고속 배칭)으로 번역을 처리하는 코어 매핑 엔진
    """
    batch_map = {}
    if not chunk:
        return batch_map

    # 1. 분리된 청크 문장들을 하나의 문자열로 결합 (통신 횟수 1회로 단축)
    combined_text = DELIMITER.join(chunk)

    try:
        # 2. 번역기 엔진 종류별 호출 규격 방어 및 연동
        # 클래스 이름 문자열을 확인하여 분기 처리
        translator_type = translator.__class__.__name__

        if translator_type == "LocalNLLBTranslator":
            # 내가 만든 로컬 고속 서버용 호출
            translated_combined = translator.translate(combined_text, src_lang="en", dest_lang="ko")

        elif translator_type == "GeminiTranslator":
            # Gemini API용 호출
            translated_combined = translator.translate(combined_text, src_lang="en", dest_lang="ko")

        elif translator_type == "GoogleTranslator":
            # deep_translator 구글 무료용 호출 (text 인자만 단일 주입)
            translated_combined = translator.translate(text=combined_text)

        elif translator_type == "PapagoTranslator":
            # deep_translator 파파고용 호출
            translated_combined = translator.translate(text=combined_text)

        elif translator_type == "ChatGptTranslator":
            # deep_translator ChatGPT용 호출
            translated_combined = translator.translate(text=combined_text)

        else:
            # 기타 예외 엔진 처리 방어선
            if hasattr(translator, 'translate'):
                translated_combined = translator.translate(text=combined_text)
            else:
                raise AttributeError("지원하지 않는 번역기 인터페이스입니다.")

        # 3. 통째로 번역되어 돌아온 문자열을 다시 각각의 문장 라인으로 쪼갬
        translated_lines = translated_combined.split(DELIMITER)

        # 4. 원본 인코딩 텍스트와 번역된 텍스트를 다시 1:1 매핑 복원
        for orig_encoded, trans_encoded in zip(chunk, translated_lines):
            orig_raw = decoder_func(orig_encoded)
            trans_raw = decoder_func(trans_encoded.strip())
            batch_map[orig_raw] = trans_raw

    except Exception as e:
        print(f"\n[오류] 배치 초고속 통신 처리 중 실패: {e}")
        # 오류 발생 시 프로그램이 멈추지 않도록 원문을 그대로 반환하여 롤백 방어
        for orig_encoded in chunk:
            orig_raw = decoder_func(orig_encoded)
            batch_map[orig_raw] = orig_raw

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
                # 단어 단독 번역 요청 후 학습 명부에 기재
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
