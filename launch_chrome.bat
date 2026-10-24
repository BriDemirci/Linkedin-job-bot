@echo off
echo ========================================================
echo  LinkedIn Easy Apply Bot - Iniciando Chrome en puerto 9222
echo ========================================================
echo.

set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=chrome.exe"

echo Iniciando Google Chrome con el perfil de Bot (puerto 9222)...
echo.
echo NOTA: Si es la primera vez que se abre, inicia sesion en LinkedIn.
echo La sesion quedara guardada para siempre en este perfil.
echo.

start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\BotProfile" "https://www.linkedin.com/jobs/"
