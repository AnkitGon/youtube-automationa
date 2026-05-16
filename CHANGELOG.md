# Changelog

All notable changes to TubeAssistant are documented here.

---

## [1.0.0] — 2026-05-16

### Added
- Full autonomous YouTube pipeline: analytics → script → TTS → footage → montage → thumbnail → upload
- 15 AI providers: OpenRouter, OpenAI, Anthropic, Gemini, Mistral, Groq, DeepSeek, xAI, Cohere, Together, Perplexity, Fireworks, Azure OpenAI, Ollama Cloud, Local Ollama
- Interactive TUI menu (`tube-assistant` with arrow-key navigation)
- Telegram bot for live control: force run, queue topics, skip, analytics, status
- Guided onboarding wizard via Telegram (4-step TUI)
- Pipeline checkpoint recovery — resumes from last completed step after crash
- `uv tool install` support — fast installation via uv
- Cross-platform: Windows, Linux, macOS
- All models overridable via env vars (`OPENAI_MODEL`, `GROQ_MODEL`, etc.)
- Background music support (chill, epic, mysterious, upbeat, tense)
- Analytics-driven topic and tone adaptation
- Long-term memory (`memoria_lungo_termine.json`)
- `CONTRIBUTING.md` and `LICENSE` (MIT)
