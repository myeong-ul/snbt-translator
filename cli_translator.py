import os
import re
import sys
from dotenv import load_dotenv, set_key
from deep_translator import GoogleTranslator, PapagoTranslator, ChatGptTranslator

# .env 파일 경로 지정
ENV_FILE = "api.env"


def load_or_request_api_key(key_name, provider_name):
    """env 파일에서 키를 읽어오고, 없으면 입력받아 env 파일에 저장합니다."""
    load_dotenv(ENV_FILE)
    api_key = os.getenv(key_name)

    if not api_key:
        print(f"\n[안내] {provider_name} API 키가 {ENV_FILE} 파일에 존재하지 않습니다.")
        api_key = input(f"➔ {provider_name} API 키를 입력해주세요: ").strip()

        # 입력받은 키를 api.env 파일에 자동 생성/저장
        set_key(ENV_FILE, key_name, api_key)
        print(f"➔ {ENV_FILE} 파일에 키가 성공적으로 저장되었습니다.\n")

    return api_key


def protect_color_codes(text):
    pattern = re.compile(r'&([a-zA-Z0-9])')
    return pattern.sub(r'___CLR_\1___', text)


def restore_color_codes(text):
    pattern = re.compile(r'___CLR_([a-zA-Z0-9])___')
    text = re.sub(r'___\s*CLR_\s*([a-zA-Z0-9])\s*___', r'&\1', text)
    return pattern.sub(r'&\1', text)


def print_progress_bar(current, total, bar_length=30):
    percent = float(current) * 100 / total
    arrow = '■' * int(percent / 100 * bar_length)
    spaces = '□' * (bar_length - len(arrow))
    sys.stdout.write(f"\r진행률: [{arrow}{spaces}] {percent:.1f}% ({current}/{total} 묶음 완료)")
    sys.stdout.flush()


def main():
    input_path = "en_us.snbt"
    output_path = "ko_kr.snbt"

    if not os.path.exists(input_path):
        print(f"오류: {input_path} 파일이 존재하지 않습니다.")
        return

    # ----------------------------------------------------
    # 번역기 선택 메뉴
    # ----------------------------------------------------
    print("=" * 40)
    print(" 사용할 번역기를 선택해 주세요.")
    print(" 1. Google 번역 (무료 / 안정적)")
    print(" 2. Naver Papago (API 키 필요)")
    print(" 3. OpenAI ChatGPT (API 키 및 비용 필요)")
    print("=" * 40)

    choice = input("선택 (1~3): ").strip()

    translator = None
    max_batch_chars = 4000  # 번역기별 안정적인 글자수 제한

    if choice == '1':
        print("\n➔ Google 번역기를 선택하셨습니다.")
        translator = GoogleTranslator(source='en', target='ko')
        max_batch_chars = 4000

    elif choice == '2':
        print("\n➔ Naver Papago를 선택하셨습니다.")
        client_id = load_or_request_api_key("PAPAGO_CLIENT_ID", "Papago Client ID")
        client_secret = load_or_request_api_key("PAPAGO_CLIENT_SECRET", "Papago Client Secret")

        # deep_translator의 파파고 객체 생성
        translator = PapagoTranslator(client_id=client_id, secret_key=client_secret, source='en', target='ko')
        max_batch_chars = 4000  # 파파고 무료/글로벌 제한은 5,000자

    elif choice == '3':
        print("\n➔ OpenAI ChatGPT를 선택하셨습니다.")
        openai_key = load_or_request_api_key("OPENAI_API_KEY", "OpenAI API Secret Key")

        translator = ChatGptTranslator(api_key=openai_key, source='english', target='korean')
        max_batch_chars = 2500  # ChatGPT는 프롬프트 공간 확보를 위해 조금 더 작게 묶음

    else:
        print("올바른 번역기를 선택하지 않아 프로그램을 종료합니다.")
        return

    # ----------------------------------------------------
    # 파일 읽기 및 문장 추출
    # ----------------------------------------------------
    print("\n파일을 읽는 중...")
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
    matches = pattern.findall(content)
    unique_matches = list(set(matches))
    print(f"총 문장 수: {len(matches)}개 (중복 제외 유니크 문장: {len(unique_matches)}개)")

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
    print(f"➔ 문장들을 {total_chunks}개의 묶음으로 결합했습니다. 번역 시작...\n")

    # 예외 대상 문자열 사전 등록
    translated_map = {}
    for text in matches:
        if not text.strip() or text.startswith('{@'):
            translated_map[text] = text

    # ----------------------------------------------------
    # 묶음 번역 진행
    # ----------------------------------------------------
    for idx, chunk in enumerate(chunks):
        combined_text = DELIMITER.join(chunk)

        try:
            translated_combined = translator.translate(text=combined_text)
            translated_lines = translated_combined.split(DELIMITER)

            for orig_protected, trans_protected in zip(chunk, translated_lines):
                orig_raw = restore_color_codes(orig_protected)
                trans_raw = restore_color_codes(trans_protected.strip())
                translated_map[orig_raw] = trans_raw

        except Exception as e:
            print(f"\n[오류] {idx + 1}번째 묶음 번역 실패, 원본 유지 (원인: {e})")
            for orig_protected in chunk:
                orig_raw = restore_color_codes(orig_protected)
                translated_map[orig_raw] = orig_raw

        print_progress_bar(idx + 1, total_chunks)

    print("\n\n모든 묶음 번역 완료! 고속 파일 결합 중...")

    # 치환 및 파일 저장
    final_content = pattern.sub(lambda m: f'"{translated_map.get(m.group(1), m.group(1))}"', content)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_content)

    print(f"성공적으로 번역되어 {output_path}에 저장되었습니다!")


if __name__ == "__main__":
    main()