import os
import re
import sys

# module 패키지에서 필요한 기능들을 직접 가져옵니다.
from module import (
    extract_strings_from_file,
    save_translated_file,
    encode_text,
    decode_text,
    get_translator,
    build_batches,
    translate_batch
)

# 전 세계 주요 언어 코드 매핑 딕셔너리 (번호순)
LANG_MENU = {
    "1": ("한국어", "ko"),
    "2": ("영어", "en"),
    "3": ("일본어", "ja"),
    "4": ("중국어 (간체)", "zh-cn"),
    "5": ("중국어 (번체)", "zh-tw"),
    "6": ("러시아어", "ru"),
    "7": ("독일어", "de"),
    "8": ("프랑스어", "fr"),
    "9": ("스페인어", "es"),
    "10": ("포르투갈어", "pt"),
    "11": ("이탈리아어", "it"),
    "12": ("베트남어", "vi"),
    "13": ("태국어", "th"),
    "14": ("인도네시아어", "id"),
    "15": ("터키어", "tr")
}

# 단순 2글자 언어 코드를 마인크래프트 표준 소문자 풀코드로 변환하기 위한 매핑 사전
MC_FULL_CODE_MAP = {
    "ko": "ko_kr",
    "en": "en_us",
    "ja": "ja_jp",
    "zh": "zh_cn",
    "zh-cn": "zh_cn",
    "zh-tw": "zh_tw",
    "ru": "ru_ru",
    "de": "de_de",
    "fr": "fr_fr",
    "es": "es_es",
    "pt": "pt_pt",
    "it": "it_it",
    "vi": "vi_vn",
    "th": "th_th",
    "id": "id_id",
    "tr": "tr_tr"
}


def print_progress_bar(current, total, display_name, bar_length=30):
    percent = float(current) * 100 / total if total > 0 else 100
    arrow = '■' * int(percent / 100 * bar_length)
    spaces = '□' * (bar_length - len(arrow))
    sys.stdout.write(f"\r[{display_name}] 진행률: [{arrow}{spaces}] {percent:.1f}% ({current}/{total} 묶음 완료)")
    sys.stdout.flush()


def select_language(prompt_msg, default_code):
    """사용자에게 언어 메뉴를 보여주고 번호로 코드를 선택받습니다."""
    print(f"\n[ {prompt_msg} ]")
    print("-" * 50)

    menu_items = list(LANG_MENU.items())
    for i in range(0, len(menu_items), 3):
        row_str = ""
        for j in range(3):
            if i + j < len(menu_items):
                num, (name, code) = menu_items[i + j]
                row_str += f"{num:><2}. {name}({code})".ljust(18)
        print(row_str)
    print("16. 직접 언어 코드 입력하기")
    print("-" * 50)

    choice = input(f"➔ 선택 (기본값번호/코드 입력 가능, 기본 {default_code}): ").strip().lower()

    if not choice:
        return default_code
    if choice in LANG_MENU:
        return LANG_MENU[choice][1]
    if choice == "16":
        direct_code = input("➔ 언어 코드를 직접 입력하세요 (예: fr_fr, uk_ua): ").strip().lower()
        return direct_code if direct_code else default_code

    # 코드를 직접 타이핑한 경우 (하이픈은 마인크래프트 표준인 언더바로 변환)
    return choice.replace("-", "_")


def main():
    input_folder = "input"
    output_folder = "output"
    os.makedirs(input_folder, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    print("=" * 60)
    print(" [안내] FTB Quests & JSON 모드팩 고속 번역 툴키트")
    print(" 사용할 번역기 선택: 1.Google(무료) | 2.Papago | 3.ChatGPT")
    print("=" * 60)
    choice = input("선택 (1~3): ").strip()

    src_lang = select_language("출발(원본) 언어를 선택하세요", "en")
    dest_lang = select_language("도착(목적) 언어를 선택하세요", "ko")

    print("\n" + "-" * 50)
    skip_choice = input("➔ 챕터명 및 챕터 그룹을 번역에서 제외하시겠습니까? (y/n, 기본 y): ").strip().lower()
    skip_chapters = False if skip_choice == 'n' else True

    # 번역 코어 모듈을 통해 인스턴스 획득
    translator, max_batch_chars = get_translator(choice, src_lang, dest_lang)
    if not translator:
        print("잘못된 선택으로 종료합니다.")
        return

    # [핵심 수정] 기존의 다양한 언어코드 파일명 형태(en_us.json, zh_cn.snbt, ko.json 등)를 감지하는 정규식
    lang_code_pattern = re.compile(r'^[a-zA-Z]{2,3}([-_][a-zA-Z]{2,4})?(\.snbt|\.json)$', re.IGNORECASE)

    tasks_to_run = []
    for root, dirs, files in os.walk(input_folder):
        for file in files:
            file_name, file_ext = os.path.splitext(file)
            file_ext_lower = file_ext.lower()

            if file_ext_lower in ['.snbt', '.json']:
                full_input_path = os.path.join(root, file)
                rel_dir = os.path.relpath(root, input_folder)

                # 원본 파일명이 언어 코드 포맷인지 검증
                if lang_code_pattern.match(file):
                    # [핵심 로직] 목적 언어 코드를 완벽한 소문자 풀코드로 변환
                    target_code = dest_lang.lower().replace("-", "_")

                    # 만약 사용자가 'ko'라고만 선택했거나 메뉴에서 골랐다면 사전(MC_FULL_CODE_MAP)을 참고해 'ko_kr'로 확장
                    if len(target_code) == 2 and target_code in MC_FULL_CODE_MAP:
                        final_lang_filename = MC_FULL_CODE_MAP[target_code]
                    elif target_code in MC_FULL_CODE_MAP:
                        final_lang_filename = MC_FULL_CODE_MAP[target_code]
                    else:
                        # 직접 입력으로 이미 'fr_fr' 같은 풀코드를 넣었다면 그대로 소문자 유지
                        final_lang_filename = target_code

                    new_file_name = f"{final_lang_filename}{file_ext_lower}"
                else:
                    # 'quests.snbt' 같이 고유 개념 명칭을 가진 파일은 원본 명칭 유지
                    new_file_name = file

                full_output_path = os.path.join(output_folder, new_file_name) if rel_dir == '.' else os.path.join(
                    output_folder, rel_dir, new_file_name)

                tasks_to_run.append({
                    'input_path': full_input_path,
                    'output_path': full_output_path,
                    'display_name': os.path.join(rel_dir, file) if rel_dir != '.' else file,
                    'ext': file_ext_lower
                })

    if not tasks_to_run:
        print(f"\n[안내] '{input_folder}' 내에 번역할 파일이 없습니다.")
        return

    print(f"\n총 {len(tasks_to_run)}개의 파일을 찾았습니다. 배칭 처리를 시작합니다.\n")

    # 파일별 처리 루프
    for task in tasks_to_run:
        content, matches, skip_map = extract_strings_from_file(task['input_path'], skip_chapters)
        unique_matches = [t for t in set(matches) if not (skip_chapters and t in skip_map)]

        if not unique_matches:
            print(f"[{task['display_name']}] 번역할 문장이 없습니다. 원본 복사 중...")
            save_translated_file(task['output_path'], content, {}, task['ext'])
            continue

        chunks = build_batches(unique_matches, max_batch_chars, encode_text)
        total_chunks = len(chunks)
        print(f"[{task['display_name']}] 총 문장 {len(matches)}개 -> {total_chunks}개 배치 결합 완료.")

        translated_map = {}
        for text in matches:
            if not text.strip() or text.startswith('{@') or (skip_chapters and text in skip_map):
                translated_map[text] = text

        for idx, chunk in enumerate(chunks):
            batch_result = translate_batch(chunk, translator, decode_text)
            translated_map.update(batch_result)
            print_progress_bar(idx + 1, total_chunks, task['display_name'])

        print(f"\n[{task['display_name']}] 정렬 저장 중...")
        save_translated_file(task['output_path'], content, translated_map, task['ext'])
        print("-" * 50)

    print("\n============================================================")
    print(" 모든 하위 폴더 내 SNBT / JSON 파일들의 배치 분할 번역이 완료되었습니다!")
    print("============================================================")


if __name__ == "__main__":
    main()
