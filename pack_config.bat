@echo off
:: Pack ALL portable files into config/ for carry-forward to another machine.
:: Includes: credentials, state, preferences, and all learning/analytics data.
mkdir config 2>nul

echo Packing config files...
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
    if exist "%%f" (
        copy /Y "%%f" "config\" >nul
        echo   + %%f
    )
)
echo.
echo Done! The config\ folder has everything.
echo.
echo On the new machine:
echo   1. git clone + pip install -e .
echo   2. Copy config\ folder over
echo   3. Run: unpack_config.bat
echo   4. Run: python agent.py
