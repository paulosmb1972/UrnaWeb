@echo off
setlocal
REM ============================================================
REM Atalho para abrir o robo mini-dolar com um duplo-clique.
REM Este arquivo precisa estar na MESMA pasta do robo_mini_dolar.py
REM (a linha abaixo entra sozinho na pasta onde o .bat esta).
REM ============================================================
cd /d "%~dp0"

echo Pasta atual: %cd%
echo.

REM Carrega chaves/configuracoes locais (arquivo que NUNCA vai pro
REM Git - veja config_local.bat.exemplo para criar o seu).
if exist "config_local.bat" (
    call "config_local.bat"
) else (
    echo [AVISO] Nao encontrei "config_local.bat" nesta pasta.
    echo Copie "config_local.bat.exemplo" para "config_local.bat" e
    echo preencha com sua chave antes de continuar.
    echo.
)

if "%OPENROUTER_API_KEY%"=="" (
    echo.
    echo [ERRO] A variavel OPENROUTER_API_KEY nao esta definida.
    echo.
    echo Copie "config_local.bat.exemplo" para "config_local.bat"
    echo e coloque sua chave de verdade dentro dele.
    echo ^(config_local.bat fica de fora do Git, sua chave nao vaza^)
    echo.
    pause
    exit /b 1
)

REM Ativa o ambiente virtual, se existir (.venv ou venv).
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    if exist "venv\Scripts\activate.bat" (
        call "venv\Scripts\activate.bat"
    )
)

where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao foi encontrado no PATH deste computador.
    echo Instale o Python em https://python.org e marque a opcao
    echo "Add Python to PATH" durante a instalacao. Depois feche esta
    echo janela e clique de novo no iniciar_robo.bat.
    echo.
    pause
    exit /b 1
)

where streamlit >nul 2>nul
if errorlevel 1 (
    echo [ERRO] O comando "streamlit" nao foi encontrado.
    echo Abra um Prompt de Comando nesta pasta e rode:
    echo     pip install -r requirements.txt
    echo Depois feche esta janela e clique de novo no iniciar_robo.bat.
    echo.
    pause
    exit /b 1
)

if not exist "robo_mini_dolar.py" (
    echo [ERRO] Nao encontrei "robo_mini_dolar.py" na pasta:
    echo     %cd%
    echo Este .bat precisa estar na MESMA pasta do robo_mini_dolar.py.
    echo.
    pause
    exit /b 1
)

echo Tudo certo. Iniciando o robo mini-dolar...
echo (o navegador deve abrir sozinho em alguns segundos)
echo.
streamlit run robo_mini_dolar.py

echo.
echo O Streamlit foi encerrado.
pause
