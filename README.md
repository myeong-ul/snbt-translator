![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)

# ⛏️ Minecraft Modpack Studio (SNBT Translator)

👉 **[한국어 설명으로 바로가기 (Skip to Korean Description)](#-마인크래프트-모드팩-스튜디오-한국어)**

An all-in-one Minecraft modpack translation studio with a **web GUI**, supporting machine translation (Google, Papago, local NLLB) and AI translation (ChatGPT, Gemini, Ollama, OpenRouter, Claude). Automatically detects installed modpacks from Prism Launcher / CurseForge, scans quest files (.snbt) and mod localization files (.json), translates them, and packages the result as a resource pack ZIP.

---

## 🚀 Key Features

* **FastAPI Web GUI (Default):** Run `run.bat` / `run.sh` to launch a local web server. The browser opens automatically with an intuitive dark-themed UI.
* **Automatic Modpack Detection:** Scans Prism Launcher instances and CurseForge modpacks and displays them as cards with icons and versions.
* **8 Translation Engines:**
  * Machine: Google (free), Papago, Local NLLB (offline)
  * AI: ChatGPT, Gemini (recommended), Ollama (local), OpenRouter, Claude
* **FTB Quest & Mod Localization Support:** Parses `.snbt` quest files (FTB Quests v1.20/v1.21) and mod `.json` language files, then renames language codes automatically (e.g., `en_us` ➔ `ko_kr`).
* **Quest/Mod File Grouping:** Files are separated into "Quest files" and "Mod files" groups, with individual select-all / deselect-all buttons for each.
* **Smart Batching & Caching:** Multiple sentences are bundled into a single API call using a safe delimiter. Past translations are cached in `translation_cache.json` to avoid redundant API calls.
* **Automatic Glossary Learning:** Scans the modpack for existing translations (e.g., `ko_kr` languages) and builds a `glossary.json` to keep item/mod names consistent.
* **Local NLLB Auto Setup:** If you choose the local NLLB engine and no server is running, dependencies (torch/transformers) are installed and the server is started automatically.
* **Format & Term Protection:** Preserves Minecraft color codes (`&c`), JSON/SNBT structure, and registered glossary terms during translation.
* **Session Save/Load:** You can save the current translation settings (engine, languages, file list) and resume later.
* **Live Progress Console:** Real-time logs, ETA, progress bar, stop/cancel, log copy, and log download while translating.
* **One-Click Launchers:** `run.bat` (Windows) and `run.sh` (Linux/macOS) validate the Python environment and auto-install required packages.

---

## 🛠️ Installation & Requirements

- **Python 3.10 or higher** is required.
- The launcher scripts will automatically create/use the `.venv` virtual environment and install dependencies from `requirements.txt`.

### Required Packages (requirements.txt)
```text
deep-translator
fastapi
uvicorn
pydantic
requests
python-dotenv
openai
# For local NLLB engine (auto-installed only when needed)
torch>=2.1
transformers>=4.40
huggingface-hub>=0.23
```

---

## 💻 How to Use (Web GUI)

1. **Run the launcher script for your OS:**
   - **Windows:** Double-click `run.bat`
   - **Linux / macOS:** `chmod +x run.sh && ./run.sh`
2. The FastAPI server starts and the browser opens automatically (`http://127.0.0.1:18443`).
3. Select a detected modpack instance (Prism Launcher / CurseForge) from the grid.
4. Choose a translation engine and enter the required API key / model name (if applicable).
5. Set source/destination languages (English/Japanese → Korean currently supported).
6. (Optional) Load the file list, then select or deselect quest/mod files individually.
7. Click **번역 시작하기 (Start Translation)**.
8. Wait for live progress, then download the generated resource pack ZIP automatically.

---

## 🔒 API Configuration

API keys are entered from the web UI and saved automatically:

| Engine | Required Settings |
|---|---|
| Papago | Papago Secret Key |
| ChatGPT | OpenAI API Key, Model name |
| Gemini (recommended) | Gemini API Key, Model name (e.g., `gemini-1.5-flash`) |
| Local NLLB | (No key) Endpoint: `http://127.0.0.1:8000/translate` — auto-install/start supported |
| Ollama (local) | (No key) Endpoint & model name (e.g., `llama3.1:8b`) |
| OpenRouter | OpenRouter API Key, Model name (e.g., `anthropic/claude-3.5-sonnet`) |
| Claude | Anthropic API Key, Model name (e.g., `claude-3-5-sonnet-20241022`) |

> **Note:** OpenRouter and Claude are separate cloud services with fixed endpoints. No endpoint URL input is needed.

---

## 🧩 Supported File Types

- **FTB Quests:** `.snbt` — quest chapters, groups, and tasks (parsers for v1.20 and v1.21).
- **Mod Localization:** `.json` / `.lang` — mod language files under `config/` directories.
- Custom modpack paths can also be entered directly via CLI mode.

---

## 🖥️ CLI Mode (Optional)

You can use the classic CLI version as well:

```bash
python cli_main.py
```

CLI supports engine selection (1~8), language selection, modpack scanning, and local NLLB endpoint configuration.

---

## 📁 Project Structure

```
├── main.py                    # FastAPI web backend server
├── index.html                 # Web GUI frontend
├── cli_main.py                # CLI translation flow
├── cli_translator.py          # Modpack scanning / language file helpers
├── utils.py                   # Utility functions
├── module/
│   ├── translator_core.py     # Translation engines + batch logic
│   ├── encoder.py             # SNBT encoding/decoding
│   ├── file_handler.py        # File parsing/saving
│   ├── glossary_sync.py       # Automatic glossary learning & sync
│   ├── nllb_runtime.py        # Local NLLB endpoint management
│   ├── nllb_server.py         # Local NLLB inference server
│   ├── pre_translator.py      # Pre-translation processing
│   └── parsers/               # FTB Quest parsers (v1.20, v1.21)
├── input/                     # (CLI mode) input folder
├── output/                    # Generated resource pack ZIPs
├── temp_build/                # Temporary build directory
├── glossary.json              # Learned glossary
├── translation_cache.json     # Translation cache
├── translation_session.json   # Saved session
├── api.env                    # Saved API keys
├── run.bat                    # Windows launcher (web GUI)
├── run.sh                     # Linux/macOS launcher (web GUI)
└── requirements.txt           # Python dependencies
```

---

---

# ⛏️ 마인크래프트 모드팩 스튜디오 (한국어)

마인크래프트 모드팩 제작/번역을 위한 **올인원 번역 스튜디오**입니다. **웹 GUI**를 기본 인터페이스로 제공하며, 기계번역(Google, Papago, 로컬 NLLB)과 AI 번역(ChatGPT, Gemini, Ollama, OpenRouter, Claude)을 모두 지원합니다. Prism Launcher / CurseForge에서 설치된 모드팩을 자동으로 감지하여 퀘스트 파일(.snbt)과 모드 언어 파일(.json)을 번역하고, 리소스팩 ZIP으로 패키징합니다.

---

## 🚀 주요 기능

* **FastAPI 웹 GUI (기본):** `run.bat` / `run.sh` 실행 시 로컬 웹 서버가 기동되고 브라우저가 자동으로 열립니다. 직관적인 다크 테마 UI가 제공됩니다.
* **모드팩 자동 감지:** Prism Launcher 인스턴스와 CurseForge 모드팩을 스캔하여 아이콘·버전과 함께 카드 형태로 표시합니다.
* **8가지 번역 엔진 지원:**
  * 기계번역: Google(무료), Papago, 로컬 NLLB(오프라인)
  * AI 번역: ChatGPT, Gemini(추천), Ollama(로컬), OpenRouter, Claude
* **FTB 퀘스트 & 모드 언어 파일 지원:** `.snbt` 퀘스트 파일(FTB Quests v1.20/v1.21)과 모드 `.json` 언어 파일을 파싱하고 언어 코드를 자동 변환합니다(예: `en_us` ➔ `ko_kr`).
* **퀘스트/모드 파일 그룹 선택:** 파일 목록이 "퀘스트 파일"과 "모드 파일" 그룹으로 분리되며, 각 그룹마다 개별 **전체 선택 / 전체 해제** 버튼이 있습니다.
* **스마트 배치 & 캐시:** 여러 문장을 안전한 구분자로 묶어 한 번의 API 호출로 번역합니다. 과거 번역 결과는 `translation_cache.json`에 캐시되어 불필요한 API 호출을 줄입니다.
* **자동 용어집 학습:** 모드팩 내 기존 번역(예: `ko_kr` 언어 파일)을 스캔하여 `glossary.json`을 구축하고, 아이템/모드 이름의 일관성을 유지합니다.
* **로컬 NLLB 자동 설정:** 로컬 NLLB 엔진 선택 시 서버가 없으면 의존성(torch/transformers)을 자동 설치하고 서버를 자동 시작합니다.
* **서식 및 용어 보호망:** 마인크래프트 색상 코드(`&c`), JSON/SNBT 구조, 등록된 용어집을 번역 중에도 보존합니다.
* **세션 저장/불러오기:** 현재 번역 설정(엔진, 언어, 파일 목록)을 저장했다가 이어서 작업할 수 있습니다.
* **실시간 진행 콘솔:** 번역 중 실시간 로그, 예상 남은 시간, 진행률 바, 중지/취소, 로그 복사/저장을 지원합니다.
* **원클릭 런처:** `run.bat`(윈도우) / `run.sh`(리눅스·맥)이 Python 환경을 검사하고 필요한 패키지를 자동 설치합니다.

---

## 🛠️ 설치 및 요구사항

- **Python 3.10 이상**이 필요합니다.
- 런처 스크립트가 `.venv` 가상환경을 자동으로 생성/사용하며 `requirements.txt`의 의존성을 자동 설치합니다.

### 의존성 패키지 (requirements.txt)
```text
deep-translator
fastapi
uvicorn
pydantic
requests
python-dotenv
openai
# 로컬 NLLB 엔진용 (필요 시 자동 설치)
torch>=2.1
transformers>=4.40
huggingface-hub>=0.23
```

---

## 💻 사용 방법 (웹 GUI)

1. **운영체제에 맞는 런처를 실행합니다:**
   - **윈도우:** `run.bat` 더블 클릭
   - **리눅스 / 맥:** `chmod +x run.sh && ./run.sh`
2. FastAPI 서버가 기동되면 브라우저가 자동으로 열립니다 (`http://127.0.0.1:18443`).
3. 탐지된 모드팩 인스턴스(Prism / CurseForge)를 카드에서 선택합니다.
4. 번역 엔진을 선택하고 필요한 API 키 / 모델명을 입력합니다.
5. 출발/도착 언어를 설정합니다(현재 영어/일본어 → 한국어 지원).
6. (선택) 파일 목록을 불러와 퀘스트/모드 파일을 개별 선택 또는 해제합니다.
7. **번역 시작하기** 버튼을 클릭합니다.
8. 실시간 진행 상황을 확인한 뒤 자동 생성된 리소스팩 ZIP을 다운로드합니다.

---

## 🔒 API 키 설정 안내

API 키는 웹 UI에서 입력하면 자동 저장됩니다:

| 엔진 | 필요 입력 |
|---|---|
| Papago | Papago Secret Key |
| ChatGPT | OpenAI API Key, 모델명 |
| Gemini (추천) | Gemini API Key, 모델명 (예: `gemini-1.5-flash`) |
| 로컬 NLLB | (키 불필요) 엔드포인트: `http://127.0.0.1:8000/translate` — 자동 설치/기동 지원 |
| Ollama (로컬) | (키 불필요) 엔드포인트 및 모델명 (예: `llama3.1:8b`) |
| OpenRouter | OpenRouter API Key, 모델명 (예: `anthropic/claude-3.5-sonnet`) |
| Claude | Anthropic API Key, 모델명 (예: `claude-3-5-sonnet-20241022`) |

> **참고:** OpenRouter와 Claude는 각각 다른 클라우드 서비스로, 엔드포인트가 고정되어 있어 별도 URL 입력이 필요하지 않습니다.

---

## 🧩 지원 파일 형식

- **FTB 퀘스트:** `.snbt` — 퀘스트 챕터/그룹/태스크 (v1.20, v1.21 파서 지원)
- **모드 언어 파일:** `.json` / `.lang` — `config/` 디렉터리 내 모드 언어 파일
- CLI 모드에서는 커스텀 모드팩 경로를 직접 입력할 수 있습니다.

---

## 🖥️ CLI 모드 (선택)

기존 CLI 버전도 그대로 사용할 수 있습니다:

```bash
python cli_main.py
```

CLI에서도 엔진 선택(1~8), 언어 선택, 모드팩 스캔, 로컬 NLLB 엔드포인트 설정이 지원됩니다.

---

## 📁 프로젝트 구조

```
├── main.py                    # FastAPI 웹 백엔드 서버
├── index.html                 # 웹 GUI 프론트엔드
├── cli_main.py                # CLI 번역 흐름
├── cli_translator.py          # 모드팩 탐색 / 언어 파일 헬퍼
├── utils.py                   # 유틸리티 함수
├── module/
│   ├── translator_core.py     # 번역 엔진 + 배치 로직
│   ├── encoder.py             # SNBT 인코딩/디코딩
│   ├── file_handler.py        # 파일 파싱/저장
│   ├── glossary_sync.py       # 자동 용어집 학습 & 동기화
│   ├── nllb_runtime.py        # 로컬 NLLB 엔드포인트 관리
│   ├── nllb_server.py         # 로컬 NLLB 추론 서버
│   ├── pre_translator.py      # 번역 전처리
│   └── parsers/               # FTB Quest 파서 (v1.20, v1.21)
├── input/                     # (CLI 모드) 입력 폴더
├── output/                    # 생성된 리소스팩 ZIP
├── temp_build/                # 임시 빌드 폴더
├── glossary.json              # 학습된 용어집
├── translation_cache.json     # 번역 캐시
├── translation_session.json   # 저장된 세션
├── api.env                    # 저장된 API 키
├── run.bat                    # 윈도우 런처 (웹 GUI)
├── run.sh                     # 리눅스/맥 런처 (웹 GUI)
└── requirements.txt           # Python 의존성