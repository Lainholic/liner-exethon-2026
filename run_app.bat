@echo off
chcp 65001 > nul
echo ========================================================
echo   [LINER .EXE-THON 2026] CareerPath AI 웹 애플리케이션
echo ========================================================
cd /d "%~dp0"
python -m streamlit run app.py
pause
