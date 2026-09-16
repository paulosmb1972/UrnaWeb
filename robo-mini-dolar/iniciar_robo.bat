@echo off
REM ============================================================
REM Atalho para abrir o robo mini-dolar com um duplo-clique.
REM Coloque este arquivo dentro da pasta robo-mini-dolar (junto
REM com robo_mini_dolar.py) — ou onde quiser, ele acha a pasta
REM certa sozinho pela proxima linha.
REM ============================================================
cd /d "%~dp0"

REM Carrega chaves/configuracoes locais (arquivo que NUNCA vai pro
REM Git — veja config_local.bat.exemplo para criar o seu).
if exist "config_local.bat" (
    call "config_local.bat"
)

if "%OPENROUTER_API_KEY%"=="" (
    echo.
    echo [AVISO] A variavel OPENROUTER_API_KEY nao esta definida.
    echo.
    echo Copie "config_local.bat.exemplo" para "config_local.bat"
    echo e coloque sua chave de verdade dentro dele.
    echo (config_local.bat fica de fora do Git, sua chave nao vaza)
    echo.
    pause
    exit /b 1
)

REM Ativa o ambiente virtual, se existir (.venv ou venv).
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

echo Iniciando o robo mini-dolar...
echo.
streamlit run robo_mini_dolar.py

echo.
echo O Streamlit foi encerrado.
pause
