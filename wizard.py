#!/usr/bin/env python3
"""
YouTube AI Agent — First-time Setup Wizard
Run once before starting the agent: python setup.py
"""

import os
import sys
import json
import re
import shutil
import asyncio
from pathlib import Path

# ── rich check (install it first if missing) ──────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.align import Align
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.rule import Rule
except ImportError:
    print("\n[!] Missing 'rich'. Installing now...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "-q"])
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.align import Align
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.rule import Rule

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    print("\n[!] Missing python-telegram-bot. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    from dotenv import set_key, dotenv_values
except ImportError:
    print("\n[!] Missing python-dotenv. Run: pip install -r requirements.txt")
    sys.exit(1)

console = Console()

ENV_FILE      = ".env"
STATE_FILE    = "state.json"
PREF_FILE     = "preferenze_video.json"
MEMORY_FILE   = "memoria_lungo_termine.json"
CREDS_FILE    = "credentials.json"
SETUP_DONE    = ".setup_done"


# ── env helpers ───────────────────────────────────────────────────────────────

def load_env() -> dict:
    if Path(ENV_FILE).exists():
        return dict(dotenv_values(ENV_FILE))
    # bootstrap from example
    if Path(".env.example").exists():
        shutil.copy(".env.example", ENV_FILE)
        return dict(dotenv_values(ENV_FILE))
    return {}


def write_env_key(key: str, value: str) -> None:
    Path(ENV_FILE).touch(exist_ok=True)
    set_key(ENV_FILE, key, value, quote_mode="never")


# ── state / pref / memory helpers ─────────────────────────────────────────────

def load_state() -> dict:
    if Path(STATE_FILE).exists():
        try:
            return json.loads(Path(STATE_FILE).read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    Path(STATE_FILE).write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_pref() -> dict:
    default = {
        "ritmo": "medio", "tono_voce": "confident", "lingua": "english",
        "stile_clip": "cinematic", "stile_thumbnail": "cinematic dramatic lighting, dark moody",
        "argomenti_preferiti": ["AI", "technology", "future tech"],
        "argomenti_evitare": [], "durata_target_minuti": 8,
        "musica_volume": 0.1, "note_libere": "",
    }
    if Path(PREF_FILE).exists():
        try:
            data = json.loads(Path(PREF_FILE).read_text(encoding="utf-8"))
            return {**default, **data}
        except Exception:
            pass
    return default


def save_pref(pref: dict) -> None:
    Path(PREF_FILE).write_text(
        json.dumps(pref, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def add_memory(text: str) -> None:
    from datetime import datetime, timezone
    memories = []
    if Path(MEMORY_FILE).exists():
        try:
            memories = json.loads(Path(MEMORY_FILE).read_text(encoding="utf-8"))
        except Exception:
            pass
    memories.append({
        "testo": text.strip(),
        "data": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    })
    Path(MEMORY_FILE).write_text(
        json.dumps(memories, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── display helpers ───────────────────────────────────────────────────────────

def header(title: str, subtitle: str = "") -> None:
    console.print()
    body = f"[bold cyan]{title}[/]"
    if subtitle:
        body += f"\n[dim]{subtitle}[/]"
    console.print(Panel(body, border_style="cyan", padding=(1, 4)))
    console.print()


def ok(msg: str):  console.print(f"  [bold green]✓[/]  {msg}")
def info(msg: str): console.print(f"  [dim cyan]→[/]  {msg}")
def warn(msg: str): console.print(f"  [bold yellow]⚠[/]  {msg}")
def err(msg: str):  console.print(f"  [bold red]✗[/]  {msg}")


# ── step 1 — AI service ───────────────────────────────────────────────────────

AI_SERVICES = {
    "1": {
        "name":       "OpenRouter",
        "desc":       "Cloud API — free tier available",
        "hint":       "Get a free key at openrouter.ai/keys",
        "service_id": "openrouter",
        "env_key":    "OPENROUTER_API_KEY",
        "url":        "https://openrouter.ai/keys",
    },
    "2": {
        "name":       "OpenAI",
        "desc":       "GPT-4o, GPT-4o-mini (paid)",
        "hint":       "Get a key at platform.openai.com/api-keys",
        "service_id": "openai",
        "env_key":    "OPENAI_API_KEY",
        "url":        "https://platform.openai.com/api-keys",
    },
    "3": {
        "name":       "Anthropic",
        "desc":       "Claude 3.5 Haiku / Sonnet (paid)",
        "hint":       "Get a key at console.anthropic.com",
        "service_id": "anthropic",
        "env_key":    "ANTHROPIC_API_KEY",
        "url":        "https://console.anthropic.com",
    },
    "4": {
        "name":       "Gemini",
        "desc":       "Google Gemini 2.0 Flash — free tier",
        "hint":       "Get a free key at aistudio.google.com/apikey",
        "service_id": "gemini",
        "env_key":    "GEMINI_API_KEY",
        "url":        "https://aistudio.google.com/apikey",
    },
    "5": {
        "name":       "Ollama Cloud",
        "desc":       "Hosted nemotron-3-super model",
        "hint":       "Get a key at ollama.com",
        "service_id": "ollama_cloud",
        "env_key":    "OLLAMA_API_KEY",
        "url":        "https://ollama.com",
    },
    "6": {
        "name":       "Local Ollama",
        "desc":       "Run any model on your machine — free",
        "hint":       "Requires Ollama installed — ollama.com/download",
        "service_id": "ollama_local",
        "env_key":    None,
        "url":        "https://ollama.com/download",
    },
}


def _test_openrouter(key: str) -> tuple[bool, str]:
    import requests
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "meta-llama/llama-3.3-70b-instruct:free",
                  "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5},
            timeout=25,
        )
        r.raise_for_status()
        return True, ""
    except Exception as e:
        return False, str(e)[:100]


def _test_ollama_cloud(key: str) -> tuple[bool, str]:
    import requests
    try:
        r = requests.post(
            "https://ollama.com/api/chat",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "nemotron-3-super:cloud",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "stream": False, "options": {"num_predict": 5}},
            timeout=25,
        )
        r.raise_for_status()
        return True, ""
    except Exception as e:
        return False, str(e)[:100]


def _test_ollama_local(model: str) -> tuple[bool, str]:
    import requests
    try:
        r = requests.post(
            "http://localhost:11434/api/chat",
            json={"model": model,
                  "messages": [{"role": "user", "content": "Hi"}],
                  "stream": False, "options": {"num_predict": 5}},
            timeout=10,
        )
        r.raise_for_status()
        return True, ""
    except Exception as e:
        return False, str(e)[:100]


def _test_openai(key: str) -> tuple[bool, str]:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
        )
        return True, ""
    except Exception as e:
        return False, str(e)[:100]


def _test_anthropic(key: str) -> tuple[bool, str]:
    try:
        import anthropic as sdk
        client = sdk.Anthropic(api_key=key)
        client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=5,
            messages=[{"role": "user", "content": "Hi"}],
        )
        return True, ""
    except Exception as e:
        return False, str(e)[:100]


def _test_gemini(key: str) -> tuple[bool, str]:
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        model.generate_content("Hi", generation_config={"max_output_tokens": 5})
        return True, ""
    except Exception as e:
        return False, str(e)[:100]


def step_ai_service() -> None:
    console.clear()
    header("Step 1 / 4 — AI Service", "Choose which AI powers the agent")

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("#", width=3)
    table.add_column("Service", width=16)
    table.add_column("Notes")
    for k, v in AI_SERVICES.items():
        table.add_row(k, v["name"], v["desc"])
    console.print(table)
    console.print()

    choice = Prompt.ask("Choose", choices=["1", "2", "3", "4", "5", "6"], default="1")
    svc = AI_SERVICES[choice]

    write_env_key("AI_SERVICE", svc["service_id"])

    if svc["env_key"] is None:
        # local ollama
        import subprocess
        console.print()
        try:
            res = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                ok("Local Ollama found")
            else:
                warn("Ollama not responding. Start it with: ollama serve")
        except Exception:
            warn(f"Ollama not found in PATH. Install from: {svc['url']}")
        model = Prompt.ask("Model name", default="llama3.2")
        write_env_key("OLLAMA_LOCAL_MODEL", model)
        console.print()
        with Progress(SpinnerColumn(), TextColumn("[cyan]Testing..."), transient=True) as p:
            p.add_task("")
            passed, emsg = _test_ollama_local(model)
        if passed:
            ok(f"Local Ollama responding with model '{model}'")
        else:
            warn(f"Not reachable: {emsg}")
            warn("Make sure Ollama is running before starting the agent.")
    else:
        console.print()
        info(svc["hint"])
        key = Prompt.ask(f"[bold]{svc['name']} API key[/]", password=True)
        write_env_key(svc["env_key"], key)
        console.print()
        with Progress(SpinnerColumn(), TextColumn("[cyan]Testing connection..."), transient=True) as p:
            p.add_task("")
            if svc["service_id"] == "openrouter":
                passed, emsg = _test_openrouter(key)
            elif svc["service_id"] == "openai":
                passed, emsg = _test_openai(key)
            elif svc["service_id"] == "anthropic":
                passed, emsg = _test_anthropic(key)
            elif svc["service_id"] == "gemini":
                passed, emsg = _test_gemini(key)
            else:
                passed, emsg = _test_ollama_cloud(key)
        if passed:
            ok("Connection successful")
        else:
            warn(f"Could not verify ({emsg})")
            if not Confirm.ask("  Continue anyway?", default=True):
                step_ai_service()
                return

    console.print()
    Prompt.ask("[dim]Press Enter to continue[/]", default="")


# ── step 2 — pexels ───────────────────────────────────────────────────────────

def step_pexels() -> None:
    console.clear()
    header("Step 2 / 4 — Pexels API", "Free stock video clips for your videos")
    info("Create a free account and get a key at: [link]https://www.pexels.com/api/[/]")
    console.print()
    key = Prompt.ask("[bold]Pexels API key[/]")
    write_env_key("PEXELS_API_KEY", key)
    console.print()
    ok("Pexels key saved")
    console.print()
    Prompt.ask("[dim]Press Enter to continue[/]", default="")


# ── step 3 — telegram token ───────────────────────────────────────────────────

def step_telegram_token() -> str:
    console.clear()
    header("Step 3 / 4 — Telegram Bot", "Your live control interface")

    console.print("  [bold]How to create a bot:[/]")
    console.print("  1. Open Telegram and start a chat with [cyan]@BotFather[/]")
    console.print("  2. Send [cyan]/newbot[/] and follow the instructions")
    console.print("  3. Copy the token BotFather gives you")
    console.print()

    token = Prompt.ask("[bold]Bot token[/]")
    write_env_key("TELEGRAM_BOT_TOKEN", token)

    # quick verify token format
    if not re.match(r"^\d+:[A-Za-z0-9_-]{35,}$", token):
        warn("That doesn't look like a valid bot token — double-check it.")

    ok("Token saved")
    console.print()
    Prompt.ask("[dim]Press Enter to continue[/]", default="")
    return token


# ── step 4 — telegram onboarding (async bot) ──────────────────────────────────

_QUESTIONS_EN = [
    ("user_name",        "👋 Hi! I'm your YouTube AI Agent.\n\nFirst — what's your name?"),
    ("channel_name",     "Nice to meet you, {user_name}!\n\nWhat is the name of your YouTube channel?"),
    ("channel_topic",    "What topic or niche is the channel about?\n(e.g. AI, cooking, travel, gaming, finance...)"),
    ("channel_goals",    "What are the goals for the channel?\n(e.g. reach 10k subscribers, monetize, build a personal brand...)"),
    ("channel_genre",    "What video genre/style do you want?\n(e.g. educational, entertaining, documentary, news, shorts...)"),
    ("thumbnail_style",  "🖼 How should your thumbnails look?\n\nDescribe the visual style freely.\n\nExamples:\n• dark cinematic, dramatic lighting, deep shadows\n• bright vibrant colors, energetic pop style\n• minimalist, clean white background, bold text\n• neon futuristic, cyberpunk, glowing outlines\n• warm tones, cozy lifestyle photography"),
    ("language",         "What language should the videos be in?\n\nReply: english  or  italian"),
]

_QUESTIONS_IT = [
    ("user_name",        "👋 Ciao! Sono il tuo YouTube AI Agent.\n\nPer iniziare — come ti chiami?"),
    ("channel_name",     "Piacere, {user_name}!\n\nCome si chiama il tuo canale YouTube?"),
    ("channel_topic",    "Di che argomento o nicchia tratta il canale?\n(es. AI, cucina, viaggi, gaming, finanza...)"),
    ("channel_goals",    "Quali sono gli obiettivi del canale?\n(es. arrivare a 10k iscritti, monetizzare, costruire un personal brand...)"),
    ("channel_genre",    "Che genere/stile di video vuoi fare?\n(es. educativo, intrattenimento, documentario, news, shorts...)"),
    ("thumbnail_style",  "🖼 Come devono essere le copertine dei tuoi video?\n\nDescrivi liberamente lo stile visivo.\n\nEsempi:\n• dark cinematografico, luci drammatiche, ombre profonde\n• colori vivaci e brillanti, stile energetico pop\n• minimal, sfondo bianco pulito, testo in grassetto\n• neon futuristico, cyberpunk, luci al neon\n• toni caldi, fotografia lifestyle accogliente"),
    ("language",         "In che lingua devono essere i video?\n\nRispondi: english  oppure  italian"),
]

_CREDS_MSG_EN = (
    "🔑 *Almost done!* I need access to your YouTube channel.\n\n"
    "Follow these steps:\n"
    "1. Go to [console.cloud.google.com](https://console.cloud.google.com)\n"
    "2. Create or select a project\n"
    "3. Enable *YouTube Data API v3*\n"
    "4. Go to Credentials → Create Credentials → OAuth 2.0 Client IDs\n"
    "5. Application type: *Desktop app*\n"
    "6. Download the JSON file\n"
    "7. Send it here as a file 📎\n\n"
    "I'll handle the rest!"
)

_CREDS_MSG_IT = (
    "🔑 *Quasi fatto!* Ho bisogno di accedere al tuo canale YouTube.\n\n"
    "Segui questi passi:\n"
    "1. Vai su [console.cloud.google.com](https://console.cloud.google.com)\n"
    "2. Crea o seleziona un progetto\n"
    "3. Abilita *YouTube Data API v3*\n"
    "4. Vai su Credenziali → Crea credenziali → ID client OAuth 2.0\n"
    "5. Tipo applicazione: *App desktop*\n"
    "6. Scarica il file JSON\n"
    "7. Inviamelo qui come file 📎\n\n"
    "Penso a tutto io!"
)

_LANG_PROMPT = (
    "👋 Hi / Ciao!\n\n"
    "Choose setup language:\n"
    "• Reply [bold]english[/bold]\n"
    "• Rispondi [bold]italiano[/bold]"
)


async def run_onboarding(token: str) -> dict:
    """Runs the Telegram onboarding bot and returns collected data."""

    result: dict = {}
    done_event = asyncio.Event()

    # state machine
    state: dict = {
        "chat_id":    None,
        "phase":      "lang",   # lang → questions → creds → done
        "lang":       "en",
        "q_idx":      0,
        "answers":    {},
    }

    async def send(ctx, chat_id, text):
        await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

    async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat_id
        state["chat_id"] = chat_id
        state["phase"]   = "lang"
        await send(ctx, chat_id, _LANG_PROMPT)

    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if state["chat_id"] is None:
            await on_start(update, ctx)
            return

        chat_id = update.message.chat_id
        text = (update.message.text or "").strip()
        phase = state["phase"]

        if phase == "lang":
            lang = "it" if "ital" in text.lower() or "it" == text.lower().strip() else "en"
            state["lang"] = lang
            state["phase"] = "questions"
            state["q_idx"] = 0
            questions = _QUESTIONS_IT if lang == "it" else _QUESTIONS_EN
            await send(ctx, chat_id, questions[0][1])

        elif phase == "questions":
            questions = _QUESTIONS_IT if state["lang"] == "it" else _QUESTIONS_EN
            idx = state["q_idx"]
            key, _ = questions[idx]
            state["answers"][key] = text
            idx += 1
            state["q_idx"] = idx
            if idx < len(questions):
                _, q_text = questions[idx]
                formatted = q_text.format(**state["answers"])
                await send(ctx, chat_id, formatted)
            else:
                state["phase"] = "creds"
                msg = _CREDS_MSG_IT if state["lang"] == "it" else _CREDS_MSG_EN
                await send(ctx, chat_id, msg)

        elif phase == "creds":
            lang = state["lang"]
            reminder = (
                "Invia il file JSON di Google come *allegato* 📎"
                if lang == "it" else
                "Please send the Google JSON file as an *attachment* 📎"
            )
            await send(ctx, chat_id, reminder)

    async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if state["phase"] != "creds":
            return
        doc = update.message.document
        if not doc:
            return

        lang = state["lang"]
        tg_file = await ctx.bot.get_file(doc.file_id)
        tmp = "_creds_setup_tmp.json"
        await tg_file.download_to_drive(tmp)

        try:
            data = json.loads(Path(tmp).read_text(encoding="utf-8"))
            if "installed" not in data and "web" not in data:
                raise ValueError("not an OAuth credentials file")
            shutil.move(tmp, CREDS_FILE)
        except Exception as e:
            Path(tmp).unlink(missing_ok=True)
            bad_msg = (
                f"❌ File non valido: {e}\nRiscarica il file da Google Cloud Console."
                if lang == "it" else
                f"❌ Invalid file: {e}\nPlease re-download the JSON from Google Cloud Console."
            )
            await send(ctx, update.message.chat_id, bad_msg)
            return

        state["phase"] = "done"
        done_msg = (
            "✅ *Setup completato!*\n\nAvvia l'agente con:\n`python agent.py`\n\nA presto! 🚀"
            if lang == "it" else
            "✅ *Setup complete!*\n\nStart the agent with:\n`python agent.py`\n\nSee you there! 🚀"
        )
        await send(ctx, update.message.chat_id, done_msg)

        result.update(state["answers"])
        result["chat_id"] = str(state["chat_id"])
        result["lang"]    = lang
        done_event.set()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    await done_event.wait()

    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    return result


def step_telegram_onboarding(token: str) -> dict:
    console.clear()
    header("Step 4 / 4 — Channel Setup via Telegram", "Your AI agent will interview you")

    console.print(Panel(
        "[bold cyan]Open your Telegram bot and send /start[/]\n\n"
        "[dim]The agent will ask you a few questions about your channel,\n"
        "then guide you through connecting your Google/YouTube account.[/]",
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()
    info("Waiting for you on Telegram…")
    console.print()

    return asyncio.run(run_onboarding(token))


# ── save all results ──────────────────────────────────────────────────────────

def save_results(data: dict) -> None:
    # telegram chat id
    write_env_key("TELEGRAM_CHAT_ID", data.get("chat_id", ""))

    # language → preferenze
    lang_raw = data.get("language", "english").lower()
    lang = "italian" if ("ital" in lang_raw or "italian" in lang_raw) else "english"
    pref = load_pref()
    pref["lingua"] = lang

    # preferred topics from channel topic
    topic_raw = data.get("channel_topic", "")
    if topic_raw:
        topics = [t.strip() for t in re.split(r"[,/;]", topic_raw) if t.strip()]
        if topics:
            pref["argomenti_preferiti"] = topics[:6]

    save_pref(pref)

    # long-term memory
    # thumbnail style → preferenze
    thumb_style = data.get("thumbnail_style", "").strip()
    if thumb_style:
        pref["stile_thumbnail"] = thumb_style
        save_pref(pref)

    mappings = [
        ("user_name",        "Owner name"),
        ("channel_name",     "YouTube channel name"),
        ("channel_topic",    "Channel topic/niche"),
        ("channel_goals",    "Channel goals"),
        ("channel_genre",    "Video genre/style"),
        ("thumbnail_style",  "Thumbnail style"),
        ("language",         "Video language"),
    ]
    for key, label in mappings:
        value = data.get(key, "").strip()
        if value:
            add_memory(f"{label}: {value}")

    # mark setup done
    Path(SETUP_DONE).write_text("done", encoding="utf-8")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    console.clear()
    console.print(Panel(
        Align.center(
            "[bold cyan]YouTube AI Agent[/]\n"
            "[bold]Setup Wizard[/]\n\n"
            "[dim]Autonomous video pipeline: script → TTS → clips → montage → upload[/]\n\n"
            "[dim]This wizard configures everything in 4 steps.[/]"
        ),
        border_style="cyan",
        padding=(2, 8),
    ))
    console.print()

    if Path(SETUP_DONE).exists():
        warn("Setup already completed. Running again will overwrite previous settings.")
        if not Confirm.ask("  Continue?", default=False):
            console.print()
            info("Run [bold cyan]python agent.py[/] to start the agent.")
            console.print()
            sys.exit(0)

    if not Confirm.ask("  Start setup?", default=True):
        console.print()
        sys.exit(0)

    # ── steps ────────────────────────────────────────────────────────────────
    step_ai_service()
    step_pexels()
    token = step_telegram_token()
    data  = step_telegram_onboarding(token)
    save_results(data)

    # ── done screen ───────────────────────────────────────────────────────────
    console.clear()
    console.print(Panel(
        Align.center(
            "[bold green]✓  Setup Complete![/]\n\n"
            "[dim]All settings saved.[/]\n\n"
            "Start the agent:\n"
            "[bold cyan]python agent.py[/]\n\n"
            "Or in background:\n"
            "[bold cyan].\\avvia_agente.bat[/]"
        ),
        border_style="green",
        padding=(2, 8),
    ))
    console.print()

    table = Table(show_header=False, border_style="dim", padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value", style="cyan")
    table.add_row("AI Service",   dict(dotenv_values(ENV_FILE)).get("AI_SERVICE", "—"))
    table.add_row("Language",     data.get("language", "english"))
    table.add_row("Channel",      data.get("channel_name", "—"))
    table.add_row("Credentials",  "✓ saved" if Path(CREDS_FILE).exists() else "✗ not found")
    table.add_row("Telegram",     f"chat_id {data.get('chat_id', '—')}")
    console.print(table)
    console.print()


if __name__ == "__main__":
    main()
