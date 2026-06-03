#!/bin/bash

echo "===================================================="
echo " 시스템 환경 및 의존성 라이브러리 검사를 시작합니다..."
echo "===================================================="

# 1. 가상환경 경로 설정
VENV_PATH=""
if [ -f ".venv/bin/python" ]; then
    VENV_PATH=".venv"
elif [ -f "venv/bin/python" ]; then
    VENV_PATH="venv"
fi

# 2. 가상환경 존재 여부에 따른 패키지 설치 및 실행
if [ -n "$VENV_PATH" ]; then
    if [ -f "requirements.txt" ]; then
        echo "➔ requirements.txt를 기반으로 필요한 패키지를 확인/설치합니다..."
        $VENV_PATH/bin/pip install -r requirements.txt --quiet
    fi
    echo "➔ 가상환경 파이썬으로 프로그램을 실행합니다."
    $VENV_PATH/bin/python cli_translator.py
else
    # 3. 가상환경이 없을 때 시스템 파이썬(python3 또는 python) 검사
    PYTHON_CMD=""
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_CMD="python"
    fi

    if [ -z "$PYTHON_CMD" ]; then
        echo ""
        echo "[오류] 시스템에 파이썬(Python)이 설치되어 있지 않습니다!"
        echo "➔ 리눅스 패키지 매니저(apt, dnf 등)나 macOS의 Homebrew를 통해 파이썬을 설치해 주세요."
        echo ""
        exit 1
    fi

    # 4. 시스템 파이썬이 존재할 경우 실행
    echo "[안내] 가상환경을 찾지 못했습니다. 시스템 파이썬(${PYTHON_CMD})을 이용합니다."
    if [ -f "requirements.txt" ]; then
        echo "➔ requirements.txt를 기반으로 필요한 패키지를 확인/설치합니다..."
        $PYTHON_CMD -m pip install -r requirements.txt --quiet
    fi
    echo "➔ 시스템 파이썬으로 프로그램을 실행합니다."
    $PYTHON_CMD cli_translator.py
fi

echo ""
echo "번역 프로그램이 종료되었습니다."