# module/parsers/v1_20_parser.py
import os
from module.parsers.base_parser import BaseModpackParser


class Version120Parser(BaseModpackParser):
    def can_parse(self, quest_base_path: str) -> bool:
        # lang 폴더가 없고 chapters 폴더가 존재하면 이 모듈이 처리함
        lang_folder = os.path.join(quest_base_path, "lang")
        chapters_folder = os.path.join(quest_base_path, "chapters")
        return not os.path.exists(lang_folder) and os.path.exists(chapters_folder)

    def parse(self, config_path: str, root_path: str, src_lang: str, final_lang_code: str) -> list:
        tasks = []
        quest_base = os.path.join(config_path, "ftbquests", "quests")
        chapters_folder = os.path.join(quest_base, "chapters")

        for root, dirs, files in os.walk(chapters_folder):
            for file in files:
                if file.endswith('.snbt'):
                    full_snbt_path = os.path.join(root, file)
                    out_rel = os.path.relpath(full_snbt_path, root_path)

                    tasks.append({
                        "display_name": f"[1.20-] 퀘스트 챕터: {file}",
                        "input_path": full_snbt_path,
                        "output_rel_path": out_rel,
                        "is_quest": True,
                        "ext": ".snbt",
                        "existing_translations": {}
                    })
        return tasks