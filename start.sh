#!/usr/bin/env bash
# Start YouTube AI Agent in background (Linux/macOS)
nohup youtube-ai-agent start > ~/.youtube-ai-agent/logs/agent.log 2>&1 &
echo "Agent started (PID $!). Logs: ~/.youtube-ai-agent/logs/agent.log"
