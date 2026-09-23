@echo off
setlocal
title PostureAI V2
cd /d "%~dp0"

if not exist venv (
    echo [PostureAI] Creation de l'environnement virtuel...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo [PostureAI] Installation / mise a jour des dependances...
pip install -r requirements.txt

echo [PostureAI] Lancement de l'application...
python main.py

pause
