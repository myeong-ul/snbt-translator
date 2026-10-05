# module/parsers/base_parser.py
from abc import ABC, abstractmethod

class BaseModpackParser(ABC):
    @abstractmethod
    def can_parse(self, quest_base_path: str) -> bool:
        """해당 모드팩 구조를 이 파서가 처리할 수 있는지 여부를 반환"""
        pass

    @abstractmethod
    def parse(self, config_path: str, root_path: str, src_lang: str, final_lang_code: str) -> list:
        """버전별 환경에 맞게 번역 작업(tasks) 목록을 컴파일하여 반환"""
        pass