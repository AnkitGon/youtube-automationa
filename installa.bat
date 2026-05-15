@echo off
echo ============================================
echo  TubeAssistant — Installation
echo ============================================
echo.

REM Check if uv is available, fall back to pip
where uv >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo Using uv ^(fast installer^)...
    uv pip install -e .
) else (
    echo uv not found — installing it first...
    pip install uv -q
    uv pip install -e .
)

echo.
echo ============================================
echo  DONE. Now run the setup wizard:
echo.
echo    youtube-ai-agent onboard
echo.
echo  The wizard will guide you through:
echo   1. AI service ^(OpenRouter / OpenAI / Anthropic / Gemini / Ollama^)
echo   2. Pexels API key ^(free stock clips^)
echo   3. Telegram bot ^(your control panel^)
echo   4. Channel setup via Telegram
echo   5. Google credentials for YouTube upload
echo.
echo  After setup:
echo    youtube-ai-agent start     ^<- run daemon
echo    avvia_agente.bat           ^<- run in background
echo ============================================
pause
