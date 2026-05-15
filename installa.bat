@echo off
echo ============================================
echo  YouTube AI Agent — Installation
echo ============================================
echo.
echo Installing package (this also installs all dependencies)...
pip install -e .
echo.
echo ============================================
echo  DONE. Now run the setup wizard:
echo.
echo    youtube-ai-agent onboard
echo.
echo  The wizard will guide you through:
echo   1. Connecting an AI service (OpenRouter / Ollama)
echo   2. Getting your Pexels API key (free stock clips)
echo   3. Creating a Telegram bot (your control panel)
echo   4. Channel setup via Telegram (the agent asks you
echo      name, topic, goals, genre, language)
echo   5. Sending your Google credentials file via Telegram
echo.
echo  After setup:
echo    youtube-ai-agent start     <- run daemon
echo    avvia_agente.bat           <- run in background
echo ============================================
pause
