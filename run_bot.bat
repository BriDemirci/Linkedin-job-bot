@echo off
echo ====================================================
echo  LinkedIn Easy Apply Bot - Iniciando...
echo ====================================================
echo.

REM Activar entorno virtual si existe
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo Entorno virtual activado.
) else (
    echo [AVISO] No se encontro venv. Usando Python global.
    echo Para crear el entorno: python -m venv venv
    echo Para instalar dependencias: pip install -r requirements.txt
    echo.
)

REM Verificar que .env existe
if not exist ".env" (
    echo [ERROR] Archivo .env no encontrado.
    echo Copia .env.example a .env y completa tu GEMINI_API_KEY.
    pause
    exit /b 1
)

REM Ejecutar el bot en modo automatico
echo Iniciando LinkedIn Easy Apply Bot en modo AUTO...
echo (Usa --dry-run para auditar sin postular)
echo (Usa --interactive para confirmar cada postulacion)
echo.

python main.py --auto %*

echo.
echo Bot finalizado.
pause
