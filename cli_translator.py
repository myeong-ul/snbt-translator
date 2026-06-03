import os
import re
import sys
from deep_translator import GoogleTranslator


def protect_color_codes(text):
    pattern = re.compile(r'&([a-zA-Z0-9])')
    return pattern.sub(r'___CLR_\1___', text)


def restore_color_codes(text):
    pattern = re.compile(r'___CLR_([a-zA-Z0-9])___')
    # 혹시 모를 공백 제거 처리
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

    print("파일을 읽는 중...")
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 큰따옴표 안의 문자열 추출
    pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
    matches = pattern.findall(content)

    # 중복 제거를 통해 번역할 유니크한 문장만 추출 (성능 추가 향상)
    unique_matches = list(set(matches))
    print(f"총 문장 수: {len(matches)}개 (중복 제외 유니크 문장: {len(unique_matches)}개)")

    # 1. 문장들을 묶는 작업
    chunks = []
    current_chunk = []
    current_length = 0

    # 각 문장 간의 구분을 위한 특수 구분자
    DELIMITER = "\n[=]\n"

    for text in unique_matches:
        # 번역 제외 대상 처리
        if not text.strip() or text.startswith('{@'):
            continue

        protected = protect_color_codes(text)
        # 구분자를 포함한 예상 길이를 계산
        estimated_len = len(protected) + len(DELIMITER)

        # 안전하게 4000자가 넘어가면 다음 묶음으로 분리
        if current_length + estimated_len > 4000:
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

    # 2. 번역기 정의
    translator = GoogleTranslator(source='en', target='ko')
    translated_map = {}

    # 예외/제외 대상 문자열들은 원본 그대로 맵에 미리 등록
    for text in matches:
        if not text.strip() or text.startswith('{@'):
            translated_map[text] = text

    # 3. 묶음 단위로 대량 번역 진행
    for idx, chunk in enumerate(chunks):
        # 여러 문장을 하나의 거대한 텍스트로 결합
        combined_text = DELIMITER.join(chunk)

        try:
            # 단 한 번의 요청으로 수십 개의 문장을 한 번에 번역
            translated_combined = translator.translate(text=combined_text)

            # 번역된 텍스트를 다시 각 문장으로 분리
            translated_lines = translated_combined.split(DELIMITER)

            # 원본 영어 문장과 번역된 한글 문장을 매핑 딕셔너리에 저장
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

    # 4. 정규식 패턴에 매칭되는 부분을 번역된 텍스트로 고속 치환
    final_content = pattern.sub(lambda m: f'"{translated_map.get(m.group(1), m.group(1))}"', content)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_content)

    print(f"성공적으로 번역되어 {output_path}에 저장되었습니다!")


if __name__ == "__main__":
    main()
