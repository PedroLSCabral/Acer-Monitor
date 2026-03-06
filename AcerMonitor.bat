@echo off
:: Acer Crash Monitor — Launcher
:: Eleva para administrador automaticamente e abre menu de comandos

:: ── Ajuste este caminho para a pasta do projeto ──────────────
set PROJECT_DIR=C:\Users\Pedro\Code\Pessoal\SoftwareMonitor
:: ─────────────────────────────────────────────────────────────

:: Verifica se já está rodando como admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando permissao de administrador...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%PROJECT_DIR%"

:menu
cls
echo ================================================
echo   Acer Crash Monitor
echo   Pasta: %PROJECT_DIR%
echo ================================================
echo.
echo   [1] Iniciar monitor
echo   [2] Ver status
echo   [3] Encerrar monitor
echo   [4] Gerar dashboard
echo   [5] Analisar crashes
echo   [6] Classificar reboot pendente
echo   [7] Abrir pasta do projeto
echo   [0] Sair
echo.
set /p op="Escolha: "

if "%op%"=="1" (
    echo Iniciando monitor em background...
    start "" pythonw monitor.py
    echo Monitor iniciado.
    pause
    goto menu
)
if "%op%"=="2" (
    python monitor.py --status
    pause
    goto menu
)
if "%op%"=="3" (
    echo Encerrando monitor...
    taskkill /f /fi "IMAGENAME eq pythonw.exe" /fi "WINDOWTITLE eq *monitor*" >nul 2>&1
    wmic process where "CommandLine like '%%monitor.py%%'" delete >nul 2>&1
    echo Monitor encerrado.
    pause
    goto menu
)
if "%op%"=="4" (
    python dashboard.py
    pause
    goto menu
)
if "%op%"=="5" (
    python analyze.py
    pause
    goto menu
)
if "%op%"=="6" (
    python classify_reboot.py
    pause
    goto menu
)
if "%op%"=="7" (
    explorer "%PROJECT_DIR%"
    goto menu
)
if "%op%"=="0" exit /b

goto menu