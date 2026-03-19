@echo off
chcp 65001 >nul
title Gofile Downloader Pro Launcher
echo =========================================
echo        Gofile Downloader GUI Pro
echo =========================================
echo.

:: 1. 파이썬 설치 여부 확인
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] 파이썬(Python)이 설치되어 있지 않거나 환경변수(PATH)에 등록되어 있지 않습니다.
    echo.
    echo 파이썬 다운로드 페이지를 엽니다.
    echo 설치 시 반드시 "Add python.exe to PATH" 옵션을 체크해주세요!
    echo 설치를 마친 후 이 프로그램을 다시 실행해주세요.
    echo.
    pause
    start https://www.python.org/downloads/
    exit /b
)

echo [정보] 파이썬이 설치되어 있습니다: 
python --version
echo.

:: 2. 필수 라이브러리(requirements.txt) 설치
echo [정보] 필수 라이브러리 설치 및 업데이트를 확인합니다...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [경고] 라이브러리 설치 중 오류가 발생했을 수 있습니다.
    echo 그래도 프로그램 실행을 계속 시도합니다.
    echo.
) else (
    echo [정보] 필수 패키지가 모두 준비되었습니다!
    echo.
)

:: 3. GUI 실행
echo [정보] Gofile Downloader Pro 프로그램(gui.py)을 실행합니다...
echo.
python gui.py

:: 프로그램이 오류로 닫힐 경우를 대비해 일시정지
pause
