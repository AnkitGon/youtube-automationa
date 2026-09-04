#!/usr/bin/env bash
# Pack portable config into config/ for moving to another machine (Linux/macOS).
set -e
cd "$(dirname "$0")"
mkdir -p config

echo "Packing config files..."
for f in \
  .env \
  credentials.json \
  token.json \
  state.json \
  shorts_state.json \
  preferenze_video.json \
  memoria_lungo_termine.json \
  channel_learning.json \
  experiments.json \
  hook_learning.json \
  title_learning.json \
  shorts_history.json \
  shorts_profiles.json \
  shorts_strategy.json \
  strategia_storia.json \
  strategy_memory.json \
  topic_history.json \
  topic_diversity.json \
  video_learnings.json \
  video_performance_profiles.json \
  state.json.bak \
  shorts_state.json.bak
do
  if [ -f "$f" ]; then
    cp -f "$f" "config/$f"
    echo "  + $f"
  fi
done

echo
echo "Done! The config/ folder has everything."
echo
echo "On the new machine:"
echo "  1. git clone + install deps"
echo "  2. Copy config/ folder over"
echo "  3. Run: ./unpack_config.sh"
echo "  4. Run: python3 agent.py"
