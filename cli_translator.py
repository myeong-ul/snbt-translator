import os
import re
import sys
from dotenv import load_dotenv, set_key
from deep_translator import GoogleTranslator, PapagoTranslator, ChatGptTranslator

ENV_FILE = "api.env"

# ====================================================
# 번역 제외 고유명사 리스트 (필요시 추가)
# ====================================================
PROPER_NOUNS = [
    "Ad Astra",
    "Mekanism",
    "Netherite",
    "Mithril",
    "Steel Ingot",
    "Redstone"
]


def protect_proper_nouns(text):
    protected_text = text
    sorted_nouns = sorted(PROPER_NOUNS, key=len, reverse=True)
    for idx, noun in enumerate(sorted_nouns):
        pattern = re.compile(rf'\b{re.escape(noun)}\b', re.IGNORECASE)
        protected_text = pattern.sub(f'___NOUN_{idx}___', protected_text)
    return protected_text


def restore_proper_nouns(text):
    restored_text = text
    sorted_nouns = sorted(PROPER_NOUNS, key=len, reverse=True)
    for idx, noun in enumerate(sorted_nouns):
        pattern = re.compile(rf'___\s*NOUN_{idx}\s*___')
        restored_text = pattern.sub(noun, restored_text)
    return restored_text


# ====================================================
# [수정] 색상 코드 보호/복원 함수 (대괄호 태그 방식으로 변경)
# ====================================================
def protect_color_codes(text):
    """ &c 구조를 번역기가 건드리지 않는 [#c] 형태로 변경합니다. """
    pattern = re.compile(r'&([a-zA-F0-9klmnoorKLMNOOR])')
    return pattern.sub(r'[#\1]', text)


def restore_color_codes(text):
    """
    [#c] 구조를 다시 &c로 되돌립니다.
    번역기가 임의로 넣을 수 있는 공백 [ # c ] 이나 [# c] 등도 모두 잡아냅니다.
    """
    # 번역기가 대괄호 내부에 공백을 집어넣었을 경우를 대비한 유연한 정규식
    pattern = re.compile(r'\[\s*#\s*([a-zA-F0-9klmnoorKLMNOOR])\s*\]')
    return pattern.sub(r'&\1', text)


def load_or_request_api_key(key_name, provider_name):
    load_dotenv(ENV_FILE)
    api_key = os.getenv(key_name)
    if not api_key:
        print(f"\n[안내] {provider_name} API 키가 {ENV_FILE} 파일에 존재하지 않습니다.")
        api_key = input(f"➔ {provider_name} API 키를 입력해주세요: ").strip()
        set_key(ENV_FILE, key_name, api_key)
        print(f"➔ {ENV_FILE} 파일에 키가 성공적으로 저장되었습니다.\n")
    return api_key


def print_progress_bar(current, total, display_name, bar_length=30):
    percent = float(current) * 100 / total if total > 0 else 100
    arrow = '■' * int(percent / 100 * bar_length)
    spaces = '□' * (bar_length - len(arrow))
    sys.stdout.write(f"\r[{display_name}] 진행률: [{arrow}{spaces}] {percent:.1f}% ({current}/{total} 묶음 완료)")
    sys.stdout.flush()


def process_file_batch(full_input_path, full_output_path, display_name, translator, max_batch_chars, skip_chapters):
    """파일 하나를 읽어 문장들을 배치(Batch)로 묶어 번역하고 지정된 경로에 저장합니다."""
    os.makedirs(os.path.dirname(full_output_path), exist_ok=True)

    with open(full_input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    string_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
    matches = string_pattern.findall(content)

    skip_map = {}
    if skip_chapters:
        snbt_meta_pattern = re.compile(r'(filename|group)\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')
        for m in snbt_meta_pattern.finditer(content):
            skip_map[m.group(2)] = True

        lang_meta_pattern = re.compile(r'(file|chapter|chapter_group)\.[a-zA-Z0-9_.]+\s*[:=]\s*"([^"\\]*(?:\\.[^"\\]*)*)"')
        for m in lang_meta_pattern.finditer(content):
            skip_map[m.group(2)] = True

    unique_matches = []
    for text in set(matches):
        if skip_chapters and text in skip_map:
            continue
        unique_matches.append(text)

    if not unique_matches:
        print(f"[{display_name}] 번역할 문장이 없습니다 (모두 제외됨). 복사 중...")
        with open(full_output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return

    # ----------------------------------------------------
    # 글자수 제한에 맞게 문장 묶기 (Batching)
    # ----------------------------------------------------
    chunks = []
    current_chunk = []
    current_length = 0
    DELIMITER = "\n[=]\n"

    for text in unique_matches:
        if not text.strip() or text.startswith('{@'):
            continue

        protected = protect_color_codes(text)
        protected = protect_proper_nouns(protected)
        estimated_len = len(protected) + len(DELIMITER)

        if current_length + estimated_len > max_batch_chars:
            chunks.append(current_chunk)
            current_chunk = [protected]
            current_length = len(protected)
        else:
            current_chunk.append(protected)
            current_length += estimated_len

    if current_chunk:
        chunks.append(current_chunk)

    total_chunks = len(chunks)
    print(f"[{display_name}] 총 문장 {len(matches)}개 -> {total_chunks}개 배치 결합 완료. 번역 시작...")

    translated_map = {}
    for text in matches:
        if not text.strip() or text.startswith('{@'):
            translated_map[text] = text
        elif skip_chapters and text in skip_map:
            translated_map[text] = text

    # ----------------------------------------------------
    # 묶음 단위 배치 번역 수행
    # ----------------------------------------------------
    for idx, chunk in enumerate(chunks):
        combined_text = DELIMITER.join(chunk)

        try:
            translated_combined = translator.translate(text=combined_text)
            translated_lines = translated_combined.split(DELIMITER)

            for orig_protected, trans_protected in zip(chunk, translated_lines):
                orig_raw = restore_proper_nouns(orig_protected)
                orig_raw = restore_color_codes(orig_raw)

                trans_raw = restore_proper_nouns(trans_protected.strip())
                trans_raw = restore_color_codes(trans_raw)

                translated_map[orig_raw] = trans_raw

        except Exception as e:
            print(f"\n[{display_name}] {idx + 1}번째 묶음 번역 실패 (원인: {e})")
            for orig_protected in chunk:
                orig_raw = restore_proper_nouns(orig_protected)
                orig_raw = restore_color_codes(orig_raw)
                translated_map[orig_raw] = orig_raw

        print_progress_bar(idx + 1, total_chunks, display_name)

    print(f"\n[{display_name}] 완료! 파일 조립 및 저장 중...")

    final_content = string_pattern.sub(lambda m: f'"{translated_map.get(m.group(1), m.group(1))}"', content)
    with open(full_output_path, 'w', encoding='utf-8') as f:
        f.write(final_content)


def main():
    input_folder = "input"
    output_folder = "output"

    os.makedirs(input_folder, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    print("=" * 60)
    print(" [안내] 주요 언어 코드 목록 (ISO 639-1)")
    print(" - 한국어: ko  |  영어: en  |  일본어: ja  |  중국어: zh")
    print("=" * 60)
    print(" 사용할 번역기를 선택해 주세요.")
    print(" 1. Google 번역 (무료)")
    print(" 2. Naver Papago (API 키 필요)")
    print(" 3. OpenAI ChatGPT (API 키 필요)")
    print("=" * 60)
    choice = input("선택 (1~3): ").strip()

    src_lang = input("➔ 원본 언어 코드를 입력하세요 (기본 en): ").strip().lower() or 'en'
    dest_lang = input("➔ 목적 언어 코드를 입력하세요 (기본 ko): ").strip().lower() or 'ko'

    print("-" * 50)
    skip_choice = input("➔ 챕터명 및 챕터 그룹을 번역에서 제외하시겠습니까? (y/n, 기본 y): ").strip().lower()
    skip_chapters = False if skip_choice == 'n' else True

    translator = None
    max_batch_chars = 4000
    llm_lang_map = {'en': 'english', 'ko': 'korean', 'ja': 'japanese', 'zh': 'chinese'}

    if choice == '1':
        print(f"\n➔ Google 번역기 세팅 ({src_lang} -> {dest_lang})")
        translator = GoogleTranslator(source=src_lang, target=dest_lang)
        max_batch_chars = 4000
    elif choice == '2':
        print(f"\n➔ Naver Papago 세팅 ({src_lang} -> {dest_lang})")
        client_id = load_or_request_api_key("PAPAGO_CLIENT_ID", "Papago Client ID")
        client_secret = load_or_request_api_key("PAPAGO_CLIENT_SECRET", "Papago Client Secret")
        translator = PapagoTranslator(client_id=client_id, secret_key=client_secret, source=src_lang, target=dest_lang)
        max_batch_chars = 4000
    elif choice == '3':
        print(f"\n➔ OpenAI ChatGPT 세팅 ({src_lang} -> {dest_lang})")
        openai_key = load_or_request_api_key("OPENAI_API_KEY", "OpenAI API Secret Key")
        s_full = llm_lang_map.get(src_lang, src_lang)
        d_full = llm_lang_map.get(dest_lang, dest_lang)
        translator = ChatGptTranslator(api_key=openai_key, source=s_full, target=d_full)
        max_batch_chars = 2500
    else:
        print("올바른 번역기를 선택하지 않아 프로그램을 종료합니다.")
        return

    lang_code_pattern = re.compile(r'^[a-zA-Z]{2}(_[a-zA-Z]{2})?\.snbt$')

    tasks_to_run = []
    for root, dirs, files in os.walk(input_folder):
        for file in files:
            if file.endswith('.snbt'):
                full_input_path = os.path.join(root, file)
                rel_dir = os.path.relpath(root, input_folder)

                if lang_code_pattern.match(file):
                    new_file_name = f"{dest_lang}_{dest_lang.lower()}.snbt" if len(
                        dest_lang) == 2 else f"{dest_lang}.snbt"
                else:
                    new_file_name = file

                if rel_dir == '.':
                    full_output_path = os.path.join(output_folder, new_file_name)
                else:
                    full_output_path = os.path.join(output_folder, rel_dir, new_file_name)

                tasks_to_run.append({
                    'input_path': full_input_path,
                    'output_path': full_output_path,
                    'display_name': os.path.join(rel_dir, file) if rel_dir != '.' else file
                })

    if not tasks_to_run:
        print(f"\n[안내] '{input_folder}' 폴더 안에 .snbt 파일이 없습니다.")
        return

    print(f"\n총 {len(tasks_to_run)}개의 파일을 찾았습니다. 배칭 처리를 시작합니다.\n")

    for task in tasks_to_run:
        process_file_batch(
            task['input_path'],
            task['output_path'],
            task['display_name'],
            translator,
            max_batch_chars,
            skip_chapters
        )
        print("-" * 50)

    print("\n" + "=" * 60)
    print(f"모든 파일의 배치 번역이 완료되어 '{output_folder}' 폴더에 저장되었습니다!")
    print("=" * 60)


if __name__ == "__main__":
    main()