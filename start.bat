@echo off
echo ========================================
echo   Bot Amazon Account - Instalador
echo   Por @PladixOficial
echo ========================================
echo.
echo Verificando e instalando dependencias...
python -m pip install --upgrade pip
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Falha ao instalar dependencias!
    pause
    exit /b %errorlevel%
)

echo.
echo Instalando navegadores Playwright...
playwright install chromium

if %errorlevel% neq 0 (
    echo.
    echo [AVISO] Falha ao instalar Playwright, mas continuando...
)

echo.
echo ========================================
echo   Iniciando o bot...
echo ========================================
echo.
python bot.py
pause
