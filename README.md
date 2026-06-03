![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)

# 🌐 FTB Quests (SNBT) Translator

👉 **[한국어 설명으로 바로가기 (Skip to Korean Description)](#-ftb-quests-snbt-번역기-korean)**

An efficient, automated, and cross-platform batch translator specifically designed for Minecraft modpack development using **FTB Quests (.snbt)** files. It supports Google Translate, Naver Papago, and OpenAI ChatGPT.

---

## 🚀 Key Features

* **Fast Batching:** Bundles multiple sentences together to maximize translation speed and minimize API requests.
* **Deep Directory Traversal:** Automatically scans all subdirectories inside `input/` and clones the exact structure into `output/`.
* **Smart Renaming:** Automatically updates language files (e.g., `en_us.snbt` ➔ `ko_KR.snbt`) while preserving unique chapter names (e.g., `quests.snbt`).
* **Chapter Skipping:** Includes an optional toggle to skip core structural strings like `chapter.ID.title` or `chapter_group.ID.title`.
* **Format & Term Protection:** Prevents corruption of Minecraft color codes (`&c`) using a bracket tag system (`[#c]`), and preserves custom mod nouns.
* **One-Click Launchers:** Formatted `run.bat` and `run.sh` scripts that validate the Python environment and auto-install requirements quietly.

---

## 🛠️ Installation & Requirements

Ensure you have Python 3.8 or higher installed on your system.

### Prerequisites (requirements.txt)
```text
deep-translator
python-dotenv
```

---

## 💻 How to Use

1. Place your target `.snbt` files into the `input/` directory (subfolders supported).
2. Execute the launcher script for your OS:
* **Windows:** Double-click `run.bat`
* **Linux / macOS:** Run `./run.sh` (Requires `chmod +x run.sh` prior to use)


3. Follow the CLI prompt to select your translator, language codes, and configuration options.
4. Collect your translated results inside the newly generated `output/` directory.

---

## 🔒 API Configuration

Premium engines (Papago, ChatGPT) will automatically prompt you for keys on first launch and save them inside an `api.env` file:

* **Naver Papago:** Requires `PAPAGO_CLIENT_ID` and `PAPAGO_CLIENT_SECRET`.
* **OpenAI ChatGPT:** Requires `OPENAI_API_KEY`.

---

---

# 🌐 FTB Quests (SNBT) 번역기 (Korean)

마인크래프트 모드팩 제작 및 개발을 위한 **FTB Quests (.snbt)** 파일 전용 고속 자동 배치 번역기입니다. Google 번역, 네이버 파파고, OpenAI ChatGPT 번역 엔진을 지원합니다.

---

## 🚀 주요 기능

* **고속 배치 번역:** 여러 문장을 하나로 묶어 번역기에 한 번에 보냄으로써 API 요청 횟수를 줄이고 번역 속도를 극대화합니다.
* **하위 폴더 유지:** `input/` 폴더 안의 모든 하위 디렉터리를 샅샅이 탐색하여 번역 후 `output/` 폴더에 원래 구조 그대로 복제합니다.
* **스마트 이름 제어:** 언어 파일 코드(예: `en_us.snbt`)는 목적지 언어(`ko_KR.snbt`)로 자동 변환하고, `quests.snbt` 같은 일반 챕터명은 그대로 유지합니다.
* **챕터 스킵 옵션:** 통합 언어 팩 변역 시 `chapter.ID.title`이나 `chapter_group.ID.title` 같은 시스템 내부 라인을 번역에서 제외할 수 있습니다.
* **서식 및 용어 보호망:** 마인크래프트 색상 코드(`&c`)를 대괄호 태그(`[#c]`)로 일시 치환하여 공백 오염을 차단하고, 등록된 고유명사를 보호합니다.
* **원클릭 런처 제공:** 파이썬 환경을 스스로 검사하고 `requirements.txt` 패키지를 백그라운드에서 자동 설치해 주는 `run.bat` 및 `run.sh`를 포함합니다.

---

## 🛠️ 설치 및 요구사항

시스템에 Python 3.8 이상의 버전이 설치되어 있어야 합니다.

### 의존성 패키지 (requirements.txt)

```text
deep-translator
python-dotenv
```

---

## 💻 사용 방법

1. 번역할 `.snbt` 파일들을 `input/` 폴더 안에 넣습니다 (하위 폴더 구조 지원).
2. 운영체제(OS)에 맞는 실행 스크립트를 구동합니다:
* **윈도우 (Windows):** `run.bat` 파일 더블 클릭
* **리눅스 / 맥 (Linux / macOS):** 터미널에서 `./run.sh` 실행 (최초 실행 전 `chmod +x run.sh` 필요)


3. 터미널 창의 안내에 따라 번역기 종류, 출발/목적 언어 코드, 챕터 스킵 여부를 선택합니다.
4. 번역이 끝나면 자동으로 생성된 `output/` 폴더에서 원래 구조 그대로 저장된 완료 파일을 확인합니다.

---

## 🔒 API 키 설정 안내

유료 API 엔진(파파고, ChatGPT) 선택 시 최초 1회만 키를 입력하면 프로젝트 폴더 내에 `api.env` 파일로 자동 저장되어 다음 실행부터는 수동 입력 없이 작동합니다.
