@echo off
chcp 65001 >nul
title Build RobRun Translator HUD
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --windowed --onefile --name RobRunTranslatorHUD --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all pynput --hidden-import=rapidocr_onnxruntime --hidden-import=pynput.keyboard._win32 src\main.py
echo.
echo Hoan tat! File EXE nam trong thu muc dist.
pause
