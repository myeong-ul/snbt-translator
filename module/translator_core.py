import os

from deep_translator import GoogleTranslator, PapagoTranslator, ChatGptTranslator
from dotenv import load_dotenv, set_key

ENV_FILE = "api.env"
DELIMITER = "\n[=]\n"


def get_translator(choice, src_lang, dest_lang):
    """선택에 따른 번역기 인스턴스와 최대 배치 글자 수를 반환합니다."""
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
        return ChatGptTranslator(api_key=openai_key, source=s_full, target=d_full), 2500

    return None, 0


def _get_or_prompt_key(key_name, provider_name):
    api_key = os.getenv(key_name)
    if not api_key:
        print(f"\n[안내] {provider_name}가 {ENV_FILE}에 없습니다.")
        api_key = input(f"➔ {provider_name} 입력: ").strip()
        set_key(ENV_FILE, key_name, api_key)
    return api_key


def build_batches(unique_strings, max_batch_chars, encoder_func):
    """문장들을 인코딩한 후, 번역기 한도에 맞춰 배치(Chunk) 목록으로 조립합니다."""
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
    """하나의 배치 묶음을 통째로 번역기로 보내고 디코딩하여 딕셔너리로 반환합니다."""
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
        # 실패 시 원본 유지 원칙
        for orig_encoded in chunk:
            orig_raw = decoder_func(orig_encoded)
            batch_map[orig_raw] = orig_raw

    return batch_map
