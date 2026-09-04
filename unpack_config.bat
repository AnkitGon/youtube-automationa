@echo off
:: Unpack config/ files back to project root.
if not exist config\ (
    echo No config\ folder found. Nothing to unpack.
    exit /b 1
)
echo Unpacking config files...
for %%f in (
    .env
    credentials.json
    token.json
    state.json
    shorts_state.json
    preferenze_video.json
    memoria_lungo_termine.json
    channel_learning.json
    experiments.json
    hook_learning.json
    title_learning.json
    shorts_history.json
    shorts_profiles.json
    shorts_strategy.json
    strategia_storia.json
    strategy_memory.json
    topic_history.json
    topic_diversity.json
    video_learnings.json
    video_performance_profiles.json
    state.json.bak
    shorts_state.json.bak
) do (
    if exist "config\%%f" (
        copy /Y "config\%%f" "%%f" >nul
        echo   + %%f
    )
)
echo.
echo Done! Run: python agent.py
