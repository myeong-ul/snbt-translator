# module/parsers/v1_21_parser.py
import os
import json
from module.parsers.base_parser import BaseModpackParser


class Version121Parser(BaseModpackParser):
    def can_parse(self, quest_base_path: str) -> bool:
        # lang 폴더가 존재하고 안에 파일이 있으면 이 모듈이 처리함
        lang_folder = os.path.join(quest_base_path, "lang")
        return os.path.exists(lang_folder) and len(os.listdir(lang_folder)) > 0

    def parse(self, config_path: str, root_path: str, src_lang: str, final_lang_code: str) -> list:
        tasks = []
        quest_base = os.path.join(config_path, "ftbquests", "quests")
        lang_folder = os.path.join(quest_base, "lang")

        # 언어 코드 변환용 서브 맵
        mapping = {"ko": "ko_kr", "en": "en_us", "ja": "ja_jp", "zh-CN": "zh_cn", "zh-TW": "zh_tw"}
        mapped_src = mapping.get(src_lang.lower(), src_lang.lower())

        src_file_json = os.path.join(lang_folder, f"{mapped_src}.json")
        src_file_snbt = os.path.join(lang_folder, f"{mapped_src}.snbt")

        target_file = src_file_json if os.path.exists(src_file_json) else (
            src_file_snbt if os.path.exists(src_file_snbt) else None)

        if not target_file:
            for f in os.listdir(lang_folder):
                if f.endswith('.json') or f.endswith('.snbt'):
                    target_file = os.path.join(lang_folder, f)
                    break

        if target_file:
            ext = os.path.splitext(target_file)[1]
            out_rel = os.path.relpath(os.path.join(lang_folder, f"{final_lang_code}{ext}"), root_path)

            existing_translations = {}
            full_out_path = os.path.join(root_path, out_rel)
            if os.path.exists(full_out_path) and ext == '.json':
                try:
                    with open(full_out_path, 'r', encoding='utf-8') as ef:
                        existing_translations = json.load(ef)
                except Exception:
                    pass

            tasks.append({
                "display_name": f"[1.21+] FTB 언어팩 ({os.path.basename(target_file)})",
                "input_path": target_file,
                "output_rel_path": out_rel,
                "is_quest": True,
                "ext": ext,
                "existing_translations": existing_translations
            })
        return tasks