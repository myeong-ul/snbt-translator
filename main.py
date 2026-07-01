import os
import re
import shutil
import sys
import zipfile
from datetime import datetime

# 분리된 커스텀 처리 모듈 로드
from utils import (
    print_progress_bar,
    select_language,
    get_final_lang_code,
    load_or_setup_launcher_paths,
    find_modpacks_deep,
    parse_target_localization_files
)

# 기존 패키지 시스템 기능 연동 (안전하게 감싸서 호출)
try:
    from module import (
        extract_strings_from_file,
        save_translated_file,
        encode_text,
        decode_text,
        get_translator,
        build_batches,
        translate_batch,
        scan_and_build_local_glossary
    )
except ImportError as e:
    print(f"\n❌ [오류] 기존 'module' 폴더의 스크립트들을 불러오지 못했습니다: {e}")
    print("현재 실행 폴더 내부에 'module' 폴더와 필수 파일들이 존재하는지 확인하세요.")
    sys.exit(1)


def main():
    output_folder = "output"
    temp_build_folder = "temp_build"

    os.makedirs(output_folder, exist_ok=True)
    if os.path.exists(temp_build_folder):
        shutil.rmtree(temp_build_folder)
    os.makedirs(temp_build_folder, exist_ok=True)

    print("\n" + "=" * 60)
    print(" [안내] 초고속 멀티 엔진 자동 번역기 (로컬 NLLB & Gemini 호환)")
    print(" 사용할 번역기 선택: ")
    print(" 1.Google(무료) | 2.Papago | 3.ChatGPT | 4.나만의 로컬 NLLB | 5.Gemini(추천)")
    print("=" * 60)
    choice = input("➔ 선택 (1~5): ").strip()

    if not choice:
        print("[안내] 선택값이 없어 프로그램을 종료합니다.")
        return

    src_lang = select_language("출발(원본) 언어를 선택하세요", "en")
    dest_lang = select_language("도착(목적) 언어를 선택하세요", "ko")
    final_lang_code = get_final_lang_code(dest_lang)

    active_launcher_paths = load_or_setup_launcher_paths()
    modpacks = find_modpacks_deep(active_launcher_paths)

    selected_pack = None
    if modpacks:
        print(f"\n[ 활성화된 모드팩 목록 (총 {len(modpacks)}개 탐색됨) ]")
        print("-" * 60)
        for idx, pack in enumerate(modpacks):
            print(f"{idx + 1}. [{pack['launcher']}] {pack['name']}")
        print(f"{len(modpacks) + 1}. 직접 모드팩 경로 입력하기")
        print("-" * 60)

        pack_choice = input(f"➔ 번역할 모드팩 번호를 선택하세요 (1~{len(modpacks) + 1}): ").strip()
        try:
            pack_idx = int(pack_choice) - 1
            if 0 <= pack_idx < len(modpacks):
                selected_pack = modpacks[pack_idx]
        except ValueError:
            pass

    if not selected_pack:
        print("\n[ 모드팩 경로 직접 수동 입력 ]")
        print("-" * 60)
        custom_path = input("➔ 모드팩 최상위 폴더 경로 직접 입력: ").strip()
        if not custom_path or not os.path.exists(custom_path):
            print("[오류] 입력 경로가 잘못되었습니다. 프로세스를 종료합니다.")
            if os.path.exists(temp_build_folder):
                shutil.rmtree(temp_build_folder)
            return

        config_path = os.path.join(custom_path, "config")
        if not os.path.exists(config_path) and os.path.exists(os.path.join(custom_path, ".minecraft", "config")):
            config_path = os.path.join(custom_path, ".minecraft", "config")
            custom_path = os.path.join(custom_path, ".minecraft")
        elif not os.path.exists(config_path) and os.path.exists(os.path.join(custom_path, "minecraft", "config")):
            config_path = os.path.join(custom_path, "minecraft", "config")
            custom_path = os.path.join(custom_path, "minecraft")

        selected_pack = {
            "launcher": "Custom", "name": os.path.basename(custom_path.rstrip("\\/")), "root_path": custom_path,
            "config_path": config_path
        }

    clean_pack_name = re.sub(r'[\/:*?"<>| ]', '_', selected_pack['name'])
    print(f"\n🎯 최종 대상 지정: [{selected_pack['launcher']}] {selected_pack['name']}")

    original_cwd = os.getcwd()
    try:
        os.chdir(selected_pack['root_path'])
        if dest_lang in ["ko_kr", "ko"]:
            scan_and_build_local_glossary()
    except Exception as e:
        print(f"[경고] 로컬 번역 병합 스킵: {e}")
    finally:
        os.chdir(original_cwd)

    skip_choice = input("\n➔ 챕터명 및 챕터 그룹을 번역에서 제외하시겠습니까? (y/n, 기본 y): ").strip().lower()
    skip_chapters = False if skip_choice == 'n' else True

    translator, max_batch_chars = get_translator(choice, src_lang, dest_lang)
    if not translator:
        if os.path.exists(temp_build_folder):
            shutil.rmtree(temp_build_folder)
        return

    # 순수 다국어 리소스 및 퀘스트 파일만 가려받기
    tasks_to_run = parse_target_localization_files(
        selected_pack['config_path'], selected_pack['root_path'], src_lang, final_lang_code
    )

    if not tasks_to_run:
        print("\n[안내] 처리 대상 순수 언어 파일 구조(.json / .snbt)를 발견하지 못했습니다.")
        if os.path.exists(temp_build_folder):
            shutil.rmtree(temp_build_folder)
        return

    print(f"\n총 {len(tasks_to_run)}개의 언어 매핑 자원을 순차 처리합니다.\n")

    for task in tasks_to_run:
        content, matches, skip_map = extract_strings_from_file(task['input_path'], skip_chapters)
        unique_matches = [t for t in set(matches) if not (skip_chapters and t in skip_map)]

        target_out_path = os.path.join(temp_build_folder, task['output_rel_path'])

        if not task['is_quest']:
            dir_name = os.path.dirname(target_out_path)
            target_out_path = os.path.join(dir_name, f"{final_lang_code}{task['ext']}")

        existing_translations = task.get('existing_translations', {})
        if existing_translations:
            unique_matches = [m for m in unique_matches if m not in existing_translations]

        if not unique_matches:
            print(f"[{task['display_name']}] 새로 번역할 문장 없음 -> 기존 기번역본 구조 복사.")
            save_translated_file(target_out_path, content, existing_translations, task['ext'])
            continue

        # 앞서 문제가 되었던 사전 고유명사 강제 학습부 안전 장치 가동
        # 만약 로컬 서버나 에러가 나면 조용히 패스하고 본 번역 진행
        try:
            from module.translator_core import scan_and_learn_nouns
            os.chdir(selected_pack['root_path'])
            # scan_and_learn_nouns(unique_matches, translator)
        except Exception:
            pass
        finally:
            os.chdir(original_cwd)

        chunks = build_batches(unique_matches, max_batch_chars, encode_text)
        total_chunks = len(chunks)
        print(f"[{task['display_name']}] 기번역 제외 새 문장 {len(unique_matches)}개 -> {total_chunks}개 배치 연동.")

        translated_map = dict(existing_translations)
        for text in matches:
            if not text.strip() or text.startswith('{@') or (skip_chapters and text in skip_map):
                translated_map[text] = text

        for idx, chunk in enumerate(chunks):
            batch_result = translate_batch(chunk, translator, decode_text)
            translated_map.update(batch_result)
            print_progress_bar(idx + 1, total_chunks, task['display_name'])

        print(f"\n[{task['display_name']}] 매핑 데이터 트리 세이브 중...")
        save_translated_file(target_out_path, content, translated_map, task['ext'])
        print("-" * 50)

    date_str = datetime.now().strftime("%m%d")
    zip_filename = f"{clean_pack_name}_{date_str}_{final_lang_code}.zip"
    final_zip_path = os.path.join(output_folder, zip_filename)

    print(f"\n📦 기번역 데이터 병합 오버라이드 팩 압축 중: {zip_filename}")
    with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_build_folder):
            for file in files:
                full_file_path = os.path.join(root, file)
                archive_name = os.path.relpath(full_file_path, temp_build_folder)
                zipf.write(full_file_path, archive_name)

    shutil.rmtree(temp_build_folder)

    print("\n============================================================")
    print(" 🎉 기번역 병합 및 타겟 최적화 배포 패키지 생성이 완료되었습니다!")
    print(f" ➔ 결과 파일: {final_zip_path}")
    print("============================================================")


if __name__ == "__main__":
    main()