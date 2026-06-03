@echo off
title SNBT Translator Launcher
chcp 65001 > nul

echo ====================================================
echo  시스템 환경 및 의존성 라이브러리 검사를 시작합니다...
echo ====================================================

:: 1. 가상환경 경로 지정 (기본 .venv 또는 venv 검색)
set VENV_PATH=
if exist .venv\Scripts\python.exe (
    set VENV_PATH=.venv
) else if exist venv\Scripts\python.exe (
    set VENV_PATH=venv
)

:: 2. 가상환경이 있으면 검사 없이 안전하게 실행
if defined VENV_PATH (
    if exist requirements.txt (
        echo ➔ requirements.txt를 기반으로 필요한 패키지를 확인/설치합니다...
        %VENV_PATH%\Scripts\pip.exe install -r requirements.txt --quiet
    )
    echo ➔ 가상환경 파이썬으로 프로그램을 실행합니다.
    %VENV_PATH%\Scripts\python.exe cli_translator.py
    goto END
)

:: 3. 가상환경이 없으면 시스템 파이썬 설치 여부 검사
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [오류] 시스템에 파이썬(Python)이 설치되어 있지 않거나 환경 변수(Path)에 등록되지 않았습니다!
    echo ➔ https://www.python.org 에서 파이썬을 설치할 때 'Add Python to PATH' 옵션을 꼭 체크해 주세요.
    echo.
    pause
    exit /b
)

:: 4. 시스템 파이썬이 존재할 경우 패키지 설치 후 실행
if exist requirements.txt (
    echo ➔ requirements.txt를 기반으로 필요한 패키지를 확인/설치합니다...
    pip install -r requirements.txt --quiet
)
echo ➔ 시스템 파이썬으로 프로그램을 실행합니다.
python cli_translator.py

:END
echo.
echo 번역 프로그램이 종료되었습니다.
pause