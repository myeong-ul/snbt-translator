import re
from module.glossary import DYNAMIC_ITEM_GLOSSARY, COMMON_ESSENTIAL_GLOSSARY

# 📌 블록/아이템 기본 한글 명칭 사전 (패턴 조립용)
# 만약 공식 단어장(DYNAMIC_ITEM_GLOSSARY)에 있으면 그걸 쓰고, 없으면 여기서 기본 방어를 해줘.
BASE_MATERIAL_MAP = {
    "granite": "화강암",
    "tuff": "응회암",
    "diorite": "섬록암",
    "andesite": "안산암",
    "deepslate": "심층암",
    "cobblestone": "조약돌",
    "sand": "모래",
    "gravel": "자갈",
    "dirt": "흙"
}


def try_pattern_translation(key: str, english_text: str) -> str:
    """
    AI 번역을 돌리기 전, 규칙적인 압축 블록 패턴을 정규식으로 감지하여
    "Nx 압축 [재질] 블록" 형태로 완벽하게 일관성 있게 자동 번역합니다.
    """
    # 예: block.craftoria.1x_compressed_granite_block 형태 분석
    # 패턴: 숫자 + x + _compressed_ + 재질 + _block
    compressed_pattern = re.compile(r'(\d+)x_compressed_([a-zA-Z0-9_]+)_block')

    match = compressed_pattern.search(key)
    if match:
        number = match.group(1)  # 예: "3"
        material_eng = match.group(2)  # 예: "granite"

        # 1. 수집해둔 마크 공식/일반 단어장에서 재질 한글 이름 찾기
        material_ko = None

        # 단어장 매핑 검사 (영문명 깔끔하게 정리해서 매치)
        clean_mat_eng = material_eng.replace("_", " ").strip().lower()

        # 공통 사전이나 일반 사전에 해당 재질이 있는지 확인
        for eng, ko in COMMON_ESSENTIAL_GLOSSARY.items():
            if eng.lower() == clean_mat_eng:
                material_ko = ko
                break

        if not material_ko:
            for eng, ko in DYNAMIC_ITEM_GLOSSARY.items():
                if eng.lower() == clean_mat_eng:
                    material_ko = ko
                    break

        # 단어장에도 없으면 기본 방어 사전에서 가져옴
        if not material_ko:
            material_ko = BASE_MATERIAL_MAP.get(clean_mat_eng, clean_mat_eng.title())

        # 2. 완벽하게 일관된 포맷으로 조립 ("3x 압축 화강암 블록")
        return f"{number}x 압축 {material_ko} 블록"

    return None  # 패턴에 맞지 않으면 None 반환 (AI 번역으로 보냄)