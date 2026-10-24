@echo off
echo ====================================================
echo  LinkedIn Easy Apply Bot - Instalacion automatica
echo ====================================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    echo Descargalo desde https://python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] Creando entorno virtual...
python -m venv venv
if errorlevel 1 (
    echo [ERROR] No se pudo crear el entorno virtual.
    pause
    exit /b 1
)

echo [2/4] Activando entorno e instalando dependencias...
call venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias.
    pause
    exit /b 1
)

echo [3/4] Instalando Playwright (Chromium)...
playwright install chromium
if errorlevel 1 (
    echo [ERROR] No se pudo instalar Playwright.
    pause
    exit /b 1
)

echo [4/4] Configurando .env...
if not exist ".env" (
    copy .env.example .env
    echo .env creado desde .env.example
    echo.
    echo IMPORTANTE: Edita .env y agrega tu GEMINI_API_KEY antes de ejecutar el bot.
) else (
    echo .env ya existe. No se sobreescribio.
)

echo.
echo ====================================================
echo  Instalacion completada exitosamente!
echo ====================================================
echo.
echo Proximos pasos:
echo   1. Edita .env y completa GEMINI_API_KEY
echo   2. Edita config/profile.json con tus datos personales
echo   3. Ejecuta launch_chrome.bat y loguea en LinkedIn
echo   4. Ejecuta run_bot.bat para iniciar el bot
echo.
pause
