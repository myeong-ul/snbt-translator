# module/translator_core.py
import os
import re

from deep_translator import GoogleTranslator, PapagoTranslator, ChatGPTTranslator
from dotenv import load_dotenv, set_key

from .encoder import load_glossary, save_glossary  # 패키지 내부 임포트

ENV_FILE = "api.env"
DELIMITER = "\n[=]\n"


def get_translator(choice, src_lang, dest_lang):
    load_dotenv(ENV_FILE)
    llm_lang_map = {'en': 'english', 'ko': 'korean', 'ja': 'japanese', 'zh': 'chinese'}

    if choice == '1':
        return GoogleTranslator(source=src_lang, target=dest_lang), 4000
    elif choice == '2':
        client_id = _get_or_prompt_key("PAPAGO_CLIENT_ID", "Papago Client ID")
        client_secret = _get_or_prompt_key("PAPAGO_CLIENT_SECRET", "Papago Client Secret")
        return PapagoTranslator(client_id=client_id, secret_key=client_secret, source=src_lang, target=dest_lang), 4000
    elif choice == '3':
        openai_key = _get_or_prompt_key("OPENAI_API_KEY", "OpenAI API Secret Key")
        s_full = llm_lang_map.get(src_lang, src_lang)
        d_full = llm_lang_map.get(dest_lang, dest_lang)
        return ChatGPTTranslator(api_key=openai_key, source=s_full, target=d_full), 2500
    return None, 0


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


def translate_batch(chunk, translator, decoder_func):
    batch_map = {}
    combined_text = DELIMITER.join(chunk)

    try:
        translated_combined = translator.translate(text=combined_text)
        translated_lines = translated_combined.split(DELIMITER)

        for orig_encoded, trans_encoded in zip(chunk, translated_lines):
            orig_raw = decoder_func(orig_encoded)
            trans_raw = decoder_func(trans_encoded.strip())
            batch_map[orig_raw] = trans_raw
    except Exception as e:
        print(f"\n[오류] 배치 번역 실패: {e}")
        for orig_encoded in chunk:
            orig_raw = decoder_func(orig_encoded)
            batch_map[orig_raw] = orig_raw

    return batch_map