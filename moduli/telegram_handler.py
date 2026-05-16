"""
Telegram bot — listens for user commands and topic suggestions.
Runs in a background thread alongside the agent daemon.
"""
import os
import json
import asyncio
import threading
import requests
import html
import shutil
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

MAX_HISTORY = 20  # messaggi per chat

_SYSTEM_PROMPT_IT = """Sei il dipendente virtuale di un canale YouTube. Il tuo capo ti parla via Telegram e tu ESEGUI quello che chiede — non spieghi perché non puoi farlo, lo fai e basta.

COSA PUOI FARE (fallo direttamente senza chiedere conferma):
- Sviluppare topic: scrivi titolo, hook, struttura, script completo
- Pianificare video: proponi e aggiungi topic in coda usando il tag [AGGIUNGI_TOPIC: testo]
- Riscrivere/migliorare script, titoli, descrizioni, tag
- Dare consigli di strategia YouTube basati sui dati
- Rispondere a qualsiasi domanda sul canale, AI, content creation

PIPELINE AUTOMATICA (ogni giorno all'ora impostata):
1. Legge analytics YouTube → adatta strategia
2. Genera topic+script via AI → audio con Edge TTS
3. Scarica clip Pexels → monta video con MoviePy → genera thumbnail
4. Carica su YouTube schedulato all'ora impostata

GESTIONE CANALE VIA COMANDI:
/forza /forzaora /skip /setpubblica /status /recap /prossimi
/coda /topic /deltopic
/canale /setdesc /video /playlist /nuovaplaylist /commenti

AZIONI REALI (tag eseguiti automaticamente — usali SEMPRE quando richiesto):
[AGGIUNGI_TOPIC: titolo] → aggiunge topic in FONDO alla coda
[PRIORITA_TOPIC: titolo] → aggiunge topic in TESTA alla coda (prossimo video)
[FORZA_ORA: titolo] → mette in testa alla coda E avvia la pipeline subito
[RINOMINA_CANALE: nuovo nome] → cambia il nome del canale YouTube via API
[AGGIORNA_DESC: testo descrizione] → aggiorna la descrizione del canale via API
[AGGIORNA_KEYWORDS: keyword1, keyword2] → aggiorna le keyword del canale via API
[RICORDA: fatto] → salva in memoria lungo termine (preferenze, info canale, istruzioni)
[SETPREF: chiave=valore] → aggiorna preferenza video. Chiavi disponibili: ritmo (lento/medio/veloce), tono_voce (confident/casual/dramatic/educational), lingua (english/italian), stile_clip (cinematic/fast cuts/minimal/documentary), stile_thumbnail (testo libero), argomenti_preferiti (lista separata da virgole), argomenti_evitare (lista separata da virgole), durata_target_minuti (numero), musica_volume (0.0-1.0), note_libere (testo libero). USA SEMPRE questo tag quando l'utente esprime una preferenza sul tipo di video (es. "voglio video più veloci" → [SETPREF: ritmo=veloce], "preferisco tono drammatico" → [SETPREF: tono_voce=dramatic], "evita di parlare di crypto" → [SETPREF: argomenti_evitare=crypto])
[DIMENTICA: testo] → rimuove dalla memoria
[VIDEO_TITOLO: video_id | nuovo titolo] → cambia titolo di un video già pubblicato
[VIDEO_DESC: video_id | nuova descrizione] → cambia descrizione di un video già pubblicato
[VIDEO_TAGS: video_id | tag1, tag2, tag3] → cambia i tag di un video già pubblicato
[VIDEO_THUMB: video_id] → ricarica la thumbnail su un video già pubblicato (usa output/thumbnail.jpg)
[ELIMINA_TOPIC: N] → rimuove il topic numero N dalla coda (1 = primo)
[RIAVVIA_MONTAGGIO] → cancella checkpoint montaggio e forza ripartenza pipeline
[BLOCCA_PIPELINE] → ferma/spegne/blocca la pipeline in corso

QUANDO USARE I TAG VIDEO:
- "cambia il titolo del video X" → [VIDEO_TITOLO: X | nuovo titolo]
- "aggiorna la descrizione del video X" → [VIDEO_DESC: X | nuova descrizione]
- "cambia i tag del video X" → [VIDEO_TAGS: X | tag1, tag2]
- "ricarica/metti la copertina al video X" → [VIDEO_THUMB: X]
- "elimina topic 2" o "rimuovi topic 1" → [ELIMINA_TOPIC: N]
- "riavvia montaggio" o "rigenera video" → [RIAVVIA_MONTAGGIO]
- "blocca", "ferma", "spegni", "stop pipeline/produzione/video" → [BLOCCA_PIPELINE]
- Per conoscere i video_id usa /video

REGOLA CRITICA SULLE RICERCHE: quando l'utente chiede notizie, aggiornamenti o informazioni recenti, usa il contesto [RICERCA WEB] già fornito nel prompt e rispondi con quei dati. NON aggiungere topic alla coda, NON usare [AGGIUNGI_TOPIC] o [FORZA_ORA] — l'utente vuole solo leggere le notizie, non produrre un video.

REGOLA CRITICA SUI TAG: usa SOLO i tag elencati sopra. NON inventare tag come [ELIMINA_TOPIC_DALLA_CODA], [GENERAZIONE_BLOCCATA], [LISTA_TOPIC], [AGGIORNA_THUMBNAIL] — questi non esistono e non vengono eseguiti. Se non esiste un tag adatto, esegui l'azione con le parole.

QUANDO USARE I TAG:
- "crea/pubblica questo video" o "fai questo adesso" → [FORZA_ORA: titolo]
- "prossimo video su X" o "metti in priorità" → [PRIORITA_TOPIC: titolo]
- "aggiungi alla coda" senza urgenza → [AGGIUNGI_TOPIC: titolo]
- Rinominare canale → [RINOMINA_CANALE: nome]
- Cambiare descrizione → [AGGIORNA_DESC: testo]
- Info/preferenze stabili → [RICORDA: fatto]
- NON usare solo [RICORDA] quando puoi agire con un tag API — AGISCI E POI ricorda

REGOLE ASSOLUTE:
- Rispondi SEMPRE nella lingua del messaggio ricevuto
- Quando ti chiedono di FARE qualcosa sul canale → usa il tag API, non spiegare
- Quando ti chiedono di sviluppare un topic → fallo subito per intero
- Non dire mai "non posso" — usa i tag disponibili o genera il contenuto
- Foto profilo: impossibile via API (limite Google)
- Nome canale: impossibile via API per account personali — di' all'utente di andare su YouTube Studio → Personalizzazione → Informazioni di base, oppure di convertire in Brand Account
"""

_SYSTEM_PROMPT_EN = """You are the virtual employee of a YouTube channel. Your boss talks to you via Telegram and you EXECUTE what they ask — you don't explain why you can't do it, you just do it.

WHAT YOU CAN DO (do it directly without asking for confirmation):
- Develop topics: write title, hook, structure, full script
- Plan videos: propose and add topics to the queue using the tag [AGGIUNGI_TOPIC: text]
- Rewrite/improve scripts, titles, descriptions, tags
- Give YouTube strategy advice based on data
- Answer any question about the channel, AI, content creation

AUTOMATIC PIPELINE (every day at the configured time):
1. Reads YouTube analytics → adapts strategy
2. Generates topic+script via AI → audio with Edge TTS
3. Downloads Pexels clips → edits video with MoviePy → generates thumbnail
4. Uploads to YouTube scheduled at the set time

CHANNEL MANAGEMENT VIA COMMANDS:
/forza /forzaora /skip /setpubblica /status /recap /prossimi
/coda /topic /deltopic
/canale /setdesc /video /playlist /nuovaplaylist /commenti

REAL ACTIONS (tags executed automatically — ALWAYS use them when requested):
[AGGIUNGI_TOPIC: title] → adds topic to the END of the queue
[PRIORITA_TOPIC: title] → adds topic to the HEAD of the queue (next video)
[FORZA_ORA: title] → puts at the head of the queue AND starts the pipeline immediately
[RINOMINA_CANALE: new name] → changes the YouTube channel name via API
[AGGIORNA_DESC: description text] → updates the channel description via API
[AGGIORNA_KEYWORDS: keyword1, keyword2] → updates channel keywords via API
[RICORDA: fact] → saves to long-term memory (preferences, channel info, instructions)
[SETPREF: key=value] → updates video preference. Available keys: ritmo (lento/medio/veloce), tono_voce (confident/casual/dramatic/educational), lingua (english/italian), stile_clip (cinematic/fast cuts/minimal/documentary), stile_thumbnail (free text), argomenti_preferiti (comma-separated list), argomenti_evitare (comma-separated list), durata_target_minuti (number), musica_volume (0.0-1.0), note_libere (free text). ALWAYS use this tag when the user expresses a preference about video type (e.g. "I want faster videos" → [SETPREF: ritmo=veloce], "I prefer dramatic tone" → [SETPREF: tono_voce=dramatic], "avoid talking about crypto" → [SETPREF: argomenti_evitare=crypto])
[DIMENTICA: text] → removes from memory
[VIDEO_TITOLO: video_id | new title] → changes the title of an already published video
[VIDEO_DESC: video_id | new description] → changes the description of an already published video
[VIDEO_TAGS: video_id | tag1, tag2, tag3] → changes the tags of an already published video
[VIDEO_THUMB: video_id] → re-uploads the thumbnail on an already published video (uses output/thumbnail.jpg)
[ELIMINA_TOPIC: N] → removes topic number N from the queue (1 = first)
[RIAVVIA_MONTAGGIO] → clears montage checkpoint and forces pipeline restart
[BLOCCA_PIPELINE] → stops/shuts down/blocks the pipeline in progress

WHEN TO USE VIDEO TAGS:
- "change the title of video X" → [VIDEO_TITOLO: X | new title]
- "update the description of video X" → [VIDEO_DESC: X | new description]
- "change the tags of video X" → [VIDEO_TAGS: X | tag1, tag2]
- "reload/put the thumbnail on video X" → [VIDEO_THUMB: X]
- "delete topic 2" or "remove topic 1" → [ELIMINA_TOPIC: N]
- "restart montage" or "regenerate video" → [RIAVVIA_MONTAGGIO]
- "block", "stop", "shut down", "stop pipeline/production/video" → [BLOCCA_PIPELINE]
- To find video_ids use /video

CRITICAL RULE ON SEARCHES: when the user asks for news, updates or recent information, use the [WEB SEARCH] context already provided in the prompt and answer with that data. Do NOT add topics to the queue, do NOT use [AGGIUNGI_TOPIC] or [FORZA_ORA] — the user just wants to read the news, not produce a video.

CRITICAL RULE ON TAGS: only use the tags listed above. Do NOT invent tags like [ELIMINA_TOPIC_DALLA_CODA], [GENERAZIONE_BLOCCATA], [LISTA_TOPIC], [AGGIORNA_THUMBNAIL] — these don't exist and won't be executed. If no suitable tag exists, perform the action with words.

WHEN TO USE TAGS:
- "create/publish this video" or "do this now" → [FORZA_ORA: title]
- "next video on X" or "prioritize" → [PRIORITA_TOPIC: title]
- "add to queue" without urgency → [AGGIUNGI_TOPIC: title]
- Rename channel → [RINOMINA_CANALE: name]
- Change description → [AGGIORNA_DESC: text]
- Stable info/preferences → [RICORDA: fact]
- Do NOT use only [RICORDA] when you can act with an API tag — ACT AND THEN remember

ABSOLUTE RULES:
- Always reply in the language of the received message
- When asked to DO something on the channel → use the API tag, don't explain
- When asked to develop a topic → do it immediately in full
- Never say "I can't" — use the available tags or generate the content
- Profile picture: impossible via API (Google limitation)
- Channel name: impossible via API for personal accounts — tell the user to go to YouTube Studio → Customization → Basic info, or to convert to a Brand Account
"""

_agent_language = os.getenv("AGENT_LANGUAGE", "english").lower()
SYSTEM_PROMPT = _SYSTEM_PROMPT_EN if _agent_language != "italian" else _SYSTEM_PROMPT_IT


def _get_history(state: dict, chat_id: str) -> list:
    return state.get("chat_history", {}).get(str(chat_id), [])


def _save_history(state: dict, chat_id: str, history: list) -> None:
    if "chat_history" not in state:
        state["chat_history"] = {}
    state["chat_history"][str(chat_id)] = history[-MAX_HISTORY:]


_SEARCH_KEYWORDS = (
    "notizie", "news", "ultime", "recenti", "oggi", "questa settimana", "questo mese",
    "cosa sta succedendo", "aggiornamenti", "novità", "annunci", "annuncio",
    "latest", "recent", "update", "updates", "what's happening", "announced",
    "uscito", "rilasciato", "lanciato", "released", "launched",
)

_ACTION_KEYWORDS = (
    "crea", "fai", "produci", "pubblica", "carica", "genera", "avvia", "lancia",
    "make", "create", "publish", "upload", "generate", "start",
    "forza", "metti in coda", "aggiungi",
)

def _needs_web_search(text: str) -> bool:
    t = text.lower()
    has_search = any(k in t for k in _SEARCH_KEYWORDS)
    has_action = any(k in t for k in _ACTION_KEYWORDS)
    # se c'è un'azione (crea video, pubblica...) non è solo ricerca
    return has_search and not has_action

def _extract_search_query(text: str) -> str:
    """Estrae la query di ricerca dal messaggio utente."""
    import re
    # cerca "su X", "riguardo X", "di X" dopo keyword di ricerca
    patterns = [
        r"notizie su (.+)",
        r"news su (.+)",
        r"aggiornamenti su (.+)",
        r"novit[àa] su (.+)",
        r"ultimissime (?:notizie )?su (.+)",
        r"cosa sta succedendo (?:con |su )?(.+)",
        r"cosa succede (?:con |su )?(.+)",
        r"cercami (.+)",
        r"cerca (.+)",
        r"dimmi (?:di |su )?(.+)",
        r"riguardo (.+)",
    ]
    t = text.lower().strip()
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return m.group(1).strip()
    # fallback: rimuovi solo le parole trigger iniziali
    for prefix in ("ultime notizie", "ultimissime notizie", "notizie", "news", "aggiornamenti"):
        if t.startswith(prefix):
            return t[len(prefix):].strip() or text
    return text


def _is_preference_list_request(text: str) -> bool:
    t = text.lower()
    return "preferenz" in t and any(k in t for k in ("mostra", "lista", "vedere", "vedi", "quali", "attuali", "dimmi"))


def _format_preference_updates(modifiche: dict) -> str:
    lines = ["✅ Preferenze aggiornate:"]
    for chiave, valore in modifiche.items():
        val = ", ".join(valore) if isinstance(valore, list) else str(valore)
        lines.append(f"• <b>{html.escape(chiave)}</b>: <code>{html.escape(val)}</code>")
    return "\n".join(lines)


def _ask_ai(user_text: str, history: list, state: dict) -> tuple[str, list]:
    from moduli.ai_client import chat_with_history
    from moduli.memoria import come_contesto
    from moduli.web_search import cerca_notizie

    system_parts = [SYSTEM_PROMPT]
    memoria = come_contesto()
    if memoria:
        system_parts.append(memoria)

    from moduli.preferenze import come_contesto as pref_contesto
    system_parts.append(pref_contesto())

    queue = state.get("topic_queue", [])
    recent = state.get("recent_topics", [])
    publish_hours = state.get("publish_hours_utc", [20])
    trigger_hours = [(h - 3) % 24 for h in publish_hours]
    vpd = state.get("videos_per_day", 1)
    video_ids = state.get("video_ids", [])
    video_links = ", ".join(f"https://youtu.be/{v}" for v in video_ids[:5]) if video_ids else "nessuno"
    is_search = _needs_web_search(user_text)
    if is_search:
        query = _extract_search_query(user_text)
        notizie = cerca_notizie(query, max_results=6)
        if notizie:
            system_parts.append(f"[RICERCA WEB IN TEMPO REALE — query: '{query}']\n{notizie}")

    system_parts.append(
        f"[CONTESTO ATTUALE — ora UTC: {datetime.now(timezone.utc).strftime('%H:%M')}]\n"
        f"Video al giorno: {vpd} | Pipeline automatica: {trigger_hours} UTC | Pubblica: {publish_hours} UTC\n"
        f"Topic in coda ({len(queue)}):\n{chr(10).join(f'  {i+1}. {t}' for i, t in enumerate(queue)) if queue else '  nessuno'}\n"
        f"IMPORTANTE: quando l'utente dice 'fai topic N' o 'crea il topic N', usa ESATTAMENTE il testo del topic numero N dalla lista sopra nel tag [FORZA_ORA: testo esatto].\n"
        f"Ultimi topic prodotti: {', '.join(recent[:5]) if recent else 'nessuno'}\n"
        f"Video pubblicati: {video_links}\n"
        f"IMPORTANTE: per rispondere su video pubblicati, scrivi direttamente i link sopra — NON usare tag [VIDEO] o simili."
    )

    system = "\n\n".join(system_parts)

    effective_text = user_text
    if is_search:
        effective_text = (
            f"[SOLO INFORMAZIONE — NON aggiungere topic, NON usare FORZA_ORA, NON usare AGGIUNGI_TOPIC, NON usare PRIORITA_TOPIC]\n"
            f"{user_text}"
        )

    try:
        reply = chat_with_history(system, history, effective_text)
    except Exception as e:
        return f"⚠️ Errore AI: {e}", history

    new_history = history + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": reply},
    ]
    return reply, new_history


def _execute_actions(reply: str, state: dict, is_search: bool = False) -> tuple[str, list, list, list]:
    """Esegue i tag azione presenti nella risposta AI."""
    import re
    from moduli.memoria import aggiungi as mem_aggiungi, _save as mem_save, _load as mem_load

    added_topics = []
    saved_memories = []
    removed_memories = []
    api_results = []

    queue = state.get("topic_queue", [])

    def _add_topic(m):
        topic = m.group(1).strip()
        queue.append(topic)
        added_topics.append(f"{topic} (in coda)")
        return ""

    def _priorita_topic(m):
        topic = m.group(1).strip()
        if not queue or queue[0] != topic:
            queue.insert(0, topic)
            added_topics.append(f"{topic} (in testa — prossimo video)")
        return ""

    def _forza_ora(m):
        topic = m.group(1).strip()
        if not queue or queue[0] != topic:
            queue.insert(0, topic)
        state["force_run"] = True
        checkpoint = "output/pipeline_checkpoint.json"
        if os.path.exists(checkpoint):
            os.remove(checkpoint)
        added_topics.append(f"{topic} (⚡ PRIORITÀ — pipeline avviata)")
        return ""

    def _ricorda(m):
        testo = m.group(1).strip()
        mem_aggiungi(testo)
        saved_memories.append(testo)
        return ""

    def _setpref(m):
        from moduli.preferenze import carica, salva, DEFAULT_PREF
        raw = m.group(1).strip()
        if "=" not in raw:
            return ""
        chiave, _, valore = raw.partition("=")
        chiave = chiave.strip()
        valore = valore.strip().strip('"').strip("'")
        if chiave not in DEFAULT_PREF:
            return ""
        pref = carica()
        default_val = DEFAULT_PREF[chiave]
        if isinstance(default_val, list):
            pref[chiave] = [v.strip() for v in valore.split(",") if v.strip()]
        elif isinstance(default_val, (int, float)):
            try:
                pref[chiave] = type(default_val)(valore)
            except ValueError:
                return ""
        else:
            pref[chiave] = valore
        salva(pref)
        api_results.append(f"⚙️ Preferenza aggiornata: <b>{chiave}</b> = <code>{pref[chiave]}</code>")
        return ""

    def _dimentica(m):
        testo = m.group(1).strip().lower()
        memories = mem_load()
        nuove = [x for x in memories if testo not in x["testo"].lower()]
        rimossi = [x["testo"] for x in memories if testo in x["testo"].lower()]
        mem_save(nuove)
        removed_memories.extend(rimossi)
        return ""

    def _rinomina_canale(m):
        from moduli.canale import aggiorna_canale
        nome = m.group(1).strip()
        try:
            res = aggiorna_canale(title=nome)
            if "title_error" in res:
                api_results.append(f"⚠️ {res['title_error']}")
            else:
                api_results.append(f"✅ Nome canale cambiato in <b>{nome}</b>")
        except Exception as e:
            api_results.append(f"❌ Errore cambio nome: {e}")
        return ""

    def _aggiorna_desc(m):
        from moduli.canale import aggiorna_canale
        desc = m.group(1).strip()
        try:
            aggiorna_canale(description=desc)
            api_results.append(f"✅ Descrizione canale aggiornata")
        except Exception as e:
            api_results.append(f"❌ Errore aggiornamento descrizione: {e}")
        return ""

    def _aggiorna_keywords(m):
        from moduli.canale import aggiorna_canale
        kw = m.group(1).strip()
        try:
            aggiorna_canale(keywords=kw)
            api_results.append(f"✅ Keyword canale aggiornate")
        except Exception as e:
            api_results.append(f"❌ Errore keyword: {e}")
        return ""

    def _video_titolo(m):
        from moduli.pubblica import aggiorna_video
        parts = m.group(1).split("|", 1)
        if len(parts) != 2:
            api_results.append("❌ Formato: [VIDEO_TITOLO: video_id | nuovo titolo]")
            return ""
        vid, titolo = parts[0].strip(), parts[1].strip()
        try:
            aggiorna_video(vid, title=titolo)
            api_results.append(f'✅ Titolo aggiornato: <a href="https://youtu.be/{vid}">{titolo}</a>')
        except Exception as e:
            api_results.append(f"❌ Errore aggiornamento titolo: {e}")
        return ""

    def _video_desc(m):
        from moduli.pubblica import aggiorna_video
        parts = m.group(1).split("|", 1)
        if len(parts) != 2:
            api_results.append("❌ Formato: [VIDEO_DESC: video_id | nuova descrizione]")
            return ""
        vid, desc = parts[0].strip(), parts[1].strip()
        try:
            aggiorna_video(vid, description=desc)
            api_results.append(f'✅ Descrizione aggiornata su <a href="https://youtu.be/{vid}">youtu.be/{vid}</a>')
        except Exception as e:
            api_results.append(f"❌ Errore aggiornamento descrizione: {e}")
        return ""

    def _video_tags(m):
        from moduli.pubblica import aggiorna_video
        parts = m.group(1).split("|", 1)
        if len(parts) != 2:
            api_results.append("❌ Formato: [VIDEO_TAGS: video_id | tag1, tag2]")
            return ""
        vid, tags_raw = parts[0].strip(), parts[1].strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        try:
            aggiorna_video(vid, tags=tags)
            api_results.append(f'✅ Tag aggiornati su <a href="https://youtu.be/{vid}">youtu.be/{vid}</a>')
        except Exception as e:
            api_results.append(f"❌ Errore aggiornamento tag: {e}")
        return ""

    def _elimina_topic(m):
        raw = m.group(1).strip()
        try:
            idx = int(raw) - 1
        except ValueError:
            api_results.append(f"❌ [ELIMINA_TOPIC] numero non valido: {raw}")
            return ""
        q = state.get("topic_queue", [])
        if idx < 0 or idx >= len(q):
            api_results.append(f"❌ Topic {raw} non esiste (coda ha {len(q)} elementi)")
            return ""
        rimosso = q.pop(idx)
        state["topic_queue"] = q
        api_results.append(f"🗑 Topic rimosso: <i>{rimosso}</i>\nRimanenti: {len(q)}")
        return ""

    def _riavvia_montaggio(m):
        checkpoint = "output/pipeline_checkpoint.json"
        if os.path.exists(checkpoint):
            os.remove(checkpoint)
        state["force_run"] = True
        api_results.append("🔄 Checkpoint cancellato — pipeline riparte dal montaggio entro 60s.")
        return ""

    def _blocca_pipeline(m):
        state["abort_pipeline"] = True
        state.pop("force_run", None)
        api_results.append("⛔ Pipeline bloccata. Si fermerà al prossimo step.")
        return ""

    def _video_thumb(m):
        from moduli.pubblica import aggiorna_video
        vid = m.group(1).strip()
        thumb = "output/thumbnail.jpg"
        if not os.path.exists(thumb):
            api_results.append("❌ Thumbnail non trovata in output/thumbnail.jpg")
            return ""
        try:
            res = aggiorna_video(vid, thumbnail_path=thumb)
            if res.get("thumbnail_error"):
                api_results.append(f"❌ Thumbnail: {res['thumbnail_error']}")
            else:
                api_results.append(f'✅ Thumbnail caricata su <a href="https://youtu.be/{vid}">youtu.be/{vid}</a>')
        except Exception as e:
            api_results.append(f"❌ Errore thumbnail: {e}")
        return ""

    if is_search:
        # rimuovi silenziosamente i tag topic — utente voleva solo info
        clean = re.sub(r'\[AGGIUNGI_TOPIC:\s*[^\]]+\]', '', reply)
        clean = re.sub(r'\[PRIORITA_TOPIC:\s*[^\]]+\]', '', clean)
        clean = re.sub(r'\[FORZA_ORA:\s*[^\]]+\]', '', clean)
    else:
        clean = re.sub(r'\[AGGIUNGI_TOPIC:\s*([^\]]+)\]', _add_topic, reply)
        clean = re.sub(r'\[PRIORITA_TOPIC:\s*([^\]]+)\]', _priorita_topic, clean)
        clean = re.sub(r'\[FORZA_ORA:\s*([^\]]+)\]', _forza_ora, clean)
    clean = re.sub(r'\[RICORDA:\s*([^\]]+)\]', _ricorda, clean)
    clean = re.sub(r'\[SETPREF:\s*([^\]]+)\]', _setpref, clean)
    clean = re.sub(r'\[DIMENTICA:\s*([^\]]+)\]', _dimentica, clean)
    clean = re.sub(r'\[RINOMINA_CANALE:\s*([^\]]+)\]', _rinomina_canale, clean)
    clean = re.sub(r'\[AGGIORNA_DESC:\s*([^\]]+)\]', _aggiorna_desc, clean)
    clean = re.sub(r'\[AGGIORNA_KEYWORDS:\s*([^\]]+)\]', _aggiorna_keywords, clean)
    clean = re.sub(r'\[VIDEO_TITOLO:\s*([^\]]+)\]', _video_titolo, clean)
    clean = re.sub(r'\[VIDEO_DESC:\s*([^\]]+)\]', _video_desc, clean)
    clean = re.sub(r'\[VIDEO_TAGS:\s*([^\]]+)\]', _video_tags, clean)
    clean = re.sub(r'\[VIDEO_THUMB:\s*([^\]]+)\]', _video_thumb, clean)
    clean = re.sub(r'\[ELIMINA_TOPIC:\s*([^\]]+)\]', _elimina_topic, clean)
    clean = re.sub(r'\[RIAVVIA_MONTAGGIO\]', _riavvia_montaggio, clean)
    clean = re.sub(r'\[BLOCCA_PIPELINE\]', _blocca_pipeline, clean)

    if added_topics:
        state["topic_queue"] = queue

    return clean.strip(), added_topics, saved_memories, removed_memories, api_results

STATE_FILE = "state.json"


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                data = f.read().strip()
            return json.loads(data) if data else {}
        except json.JSONDecodeError:
            backup = f"{STATE_FILE}.bak"
            if os.path.exists(backup):
                try:
                    with open(backup, encoding="utf-8") as f:
                        data = f.read().strip()
                    return json.loads(data) if data else {}
                except Exception:
                    pass
            return {}
    return {}


def _save_state(state: dict) -> None:
    backup = f"{STATE_FILE}.bak"
    tmp = f"{STATE_FILE}.tmp"
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                json.load(f)
            shutil.copy2(STATE_FILE, backup)
        except Exception:
            pass
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def _publish_hours(state: dict) -> list[int]:
    vpd = state.get("videos_per_day", 1)
    hours = state.get("publish_hours_utc") or [20]
    return sorted(hours)[:vpd]


def _trigger_hours(state: dict) -> list[int]:
    return sorted((h - 3) % 24 for h in _publish_hours(state))


def _next_schedule(state: dict):
    now = datetime.now(timezone.utc)
    done = state.get("runs_today", {}).get(now.strftime("%Y-%m-%d"), 0)
    if done >= state.get("videos_per_day", 1):
        now = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    publish = _publish_hours(state)
    trigger = [(h - 3) % 24 for h in publish]
    upcoming = []
    for idx, (trigger_hour, publish_hour) in enumerate(zip(trigger, publish)):
        trigger_dt = now.replace(hour=trigger_hour, minute=0, second=0, microsecond=0)
        publish_dt = now.replace(hour=publish_hour, minute=0, second=0, microsecond=0)
        if publish_dt <= trigger_dt:
            publish_dt += timedelta(days=1)
        if trigger_dt <= now:
            trigger_dt += timedelta(days=1)
            publish_dt += timedelta(days=1)
        upcoming.append((trigger_dt, publish_dt, idx))
    upcoming.sort(key=lambda item: item[0])
    return upcoming[0] if upcoming else (None, None, done)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 <b>YouTube AI Agent attivo</b>\n\n"
        "Produco e pubblico video ogni giorno in autonomia.\n\n"
        "<b>📹 Pipeline:</b>\n"
        "/status — stato attuale\n"
        "/recap — analytics ultimi video\n"
        "/forza — lancia pipeline subito\n"
        "/forzaora &lt;topic&gt; — pubblica subito senza programmazione\n"
        "/skip — salta il video di oggi\n"
        "/setvideogiorno &lt;1-5&gt; — quanti video al giorno\n"
        "/setpubblica &lt;ora1&gt; [ora2] — ora/e pubblicazione (UTC)\n"
        "/autoscheduling on|off — orari automatici da analytics\n"
        "/orari — vedi programma attuale\n"
        "/prossimi — prossimo run e prossimo publish\n"
        "/coda — topic in coda\n"
        "/topic &lt;testo&gt; — aggiungi topic\n"
        "/deltopic &lt;numero&gt; — rimuovi topic\n\n"
        "<b>📺 Canale:</b>\n"
        "/canale — info e statistiche\n"
        "/setdesc &lt;testo&gt; — aggiorna descrizione\n"
        "/video — ultimi video\n"
        "/playlist — playlist del canale\n"
        "/nuovaplaylist &lt;nome&gt; — crea playlist\n"
        "/commenti &lt;videoId&gt; — leggi commenti\n\n"
        "<b>🧠 Memoria:</b>\n"
        "/memoria — vedi cosa ricorda\n"
        "/dimentica &lt;n&gt; — rimuovi un ricordo\n\n"
        "💬 Scrivi qualsiasi cosa per parlare con l'AI.",
        parse_mode="HTML"
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    last = state.get("last_run_date", "Mai")
    queue = state.get("topic_queue", [])
    recent = state.get("recent_topics", [])
    last_video = state.get("video_ids", [None])[0]

    msg = (
        f"📡 <b>Status Agent</b>\n\n"
        f"🗓 Ultimo run: {last}\n"
        f"📋 Topic in coda: {len(queue)}\n"
        f"📹 Video prodotti: {len(state.get('video_ids', []))}\n"
    )
    if last_video:
        msg += f"🔗 Ultimo: https://youtu.be/{last_video}\n"
    if recent:
        msg += f"\n<b>Ultimi topic:</b>\n" + "\n".join(f"• {t}" for t in recent[:5])

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_preferenze(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.preferenze import formato_html
    await update.message.reply_text(formato_html(), parse_mode="HTML")


async def cmd_setpref(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.preferenze import aggiorna, DEFAULT_PREF
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "Uso: /setpref <chiave> <valore>\n"
            "Chiavi: " + ", ".join(DEFAULT_PREF.keys())
        )
        return
    chiave = ctx.args[0]
    valore = " ".join(ctx.args[1:])
    if chiave not in DEFAULT_PREF:
        await update.message.reply_text(f"Chiave sconosciuta: {chiave}\nDisponibili: {', '.join(DEFAULT_PREF.keys())}")
        return
    try:
        pref = aggiorna(chiave, valore)
    except ValueError:
        await update.message.reply_text(f"Valore non valido per {chiave}.")
        return
    await update.message.reply_text(f"✅ <b>{chiave}</b> aggiornato: <code>{pref[chiave]}</code>", parse_mode="HTML")


async def cmd_recap(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📊 Recupero analytics...")
    loop = asyncio.get_event_loop()
    try:
        from moduli.analytics import leggi_performance
        videos = await loop.run_in_executor(None, lambda: leggi_performance(n_video=10))
        if not videos:
            await update.message.reply_text("Nessun video trovato sul canale.")
            return
        lines = ["📊 <b>Performance ultimi video:</b>\n"]
        for v in videos:
            retention = int(v.get("avg_view_duration_seconds", 0) / max(v.get("duration_seconds", 480), 1) * 100)
            lines.append(
                f"▪️ <b>{v['title'][:50]}</b>\n"
                f"   👁 {v['views']} views · 👀 {v.get('impressions', 0)} impr · 📈 CTR {v.get('ctr_percent', 0)}%\n"
                f"   ❤️ {v['likes']} · 💬 {v['comments']} · ⏱ {retention}% retention · ⏰ {int(v.get('avg_view_duration_seconds', 0))}s avg"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore analytics: {e}")


async def cmd_forza(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    state["force_run"] = True
    state.pop("publish_immediately", None)
    _save_state(state)
    await update.message.reply_text("⚡ <b>Pipeline forzata!</b>\nPartirà entro 60 secondi.", parse_mode="HTML")


async def cmd_forzaora(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    topic = " ".join(ctx.args).strip() if ctx.args else ""
    state = _load_state()
    if topic:
        queue = state.get("topic_queue", [])
        queue.insert(0, topic)
        state["topic_queue"] = queue
    state["force_run"] = True
    state["publish_immediately"] = True
    _save_state(state)
    detail = f"\nTopic: <i>{html.escape(topic)}</i>" if topic else ""
    await update.message.reply_text(
        f"⚡ <b>Pipeline forzata con pubblicazione immediata.</b>{detail}\nPartirà entro 60 secondi.",
        parse_mode="HTML",
    )


async def cmd_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    vpd = state.get("videos_per_day", 1)
    runs = state.get("runs_today", {})
    runs[today] = vpd
    state["runs_today"] = runs
    state["last_run_date"] = today
    state.pop("force_run", None)
    state.pop("publish_immediately", None)
    _save_state(state)
    await update.message.reply_text(f"⏭️ Video di oggi saltati: {vpd}/{vpd}.")


async def cmd_abort(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    state["abort_pipeline"] = True
    state.pop("force_run", None)
    _save_state(state)
    await update.message.reply_text(
        "⛔ <b>Abort inviato.</b>\n\n"
        "La pipeline si fermerà al prossimo step.\n"
        "<i>Nota: se il montaggio è in corso, terminerà prima di fermarsi.</i>",
        parse_mode="HTML"
    )


async def cmd_coda(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    queue = state.get("topic_queue", [])
    if not queue:
        await update.message.reply_text("📋 Coda vuota — il prossimo topic sarà generato automaticamente.")
    else:
        msg = "📋 <b>Topic in coda:</b>\n" + "\n".join(f"{i+1}. {t}" for i, t in enumerate(queue))
        await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(ctx.args).strip() if ctx.args else ""
    if not text:
        await update.message.reply_text("Uso: /topic <testo del topic>")
        return

    state = _load_state()
    queue = state.get("topic_queue", [])
    queue.append(text)
    state["topic_queue"] = queue
    _save_state(state)

    await update.message.reply_text(
        f"✅ <b>Topic aggiunto in coda</b>\n\n"
        f"📌 <i>{text}</i>\n\n"
        f"Posizione {len(queue)} in coda.",
        parse_mode="HTML"
    )


async def cmd_setvideogiorno(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Uso: /setvideogiorno <1-5>")
        return
    try:
        n = int(ctx.args[0])
        if not 1 <= n <= 5:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Numero non valido. Usa un valore tra 1 e 5.")
        return

    publish_spreads = {1: [20], 2: [14, 20], 3: [10, 15, 20], 4: [9, 13, 17, 21], 5: [8, 11, 14, 17, 20]}

    state = _load_state()
    state["videos_per_day"] = n
    state["publish_hours_utc"] = publish_spreads[n]
    state.pop("trigger_hours_utc", None)
    _save_state(state)

    trigger_ore = [(h - 3) % 24 for h in publish_spreads[n]]
    trigger_str = ", ".join(f"{h:02d}:00" for h in trigger_ore)
    publish_str = ", ".join(f"{h:02d}:00" for h in publish_spreads[n])
    await update.message.reply_text(
        f"✅ <b>{n} video al giorno</b>\n\n"
        f"🎬 Pipeline automatica: {trigger_str} UTC\n"
        f"📅 Pubblicazione: {publish_str} UTC\n\n"
        f"Usa /autoscheduling per ottimizzare automaticamente gli orari.",
        parse_mode="HTML"
    )


async def cmd_autoscheduling(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    arg = ctx.args[0].lower() if ctx.args else ""
    if arg not in ("on", "off"):
        await update.message.reply_text("Uso: /autoscheduling on oppure /autoscheduling off")
        return
    state = _load_state()
    state["auto_scheduling"] = (arg == "on")
    _save_state(state)
    if arg == "on":
        await update.message.reply_text(
            "🤖 <b>Auto-scheduling attivo</b>\n\n"
            "L'agente analizzerà le analytics e sceglierà automaticamente gli orari migliori per pipeline e pubblicazione.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("⏹ Auto-scheduling disattivato. Orari manuali attivi.")


async def cmd_orari(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    vpd = state.get("videos_per_day", 1)
    publish = _publish_hours(state)
    trigger = [(h - 3) % 24 for h in publish]
    auto = state.get("auto_scheduling", False)
    done = state.get("runs_today", {}).get(
        __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d"), 0
    )

    trigger_str = "\n".join(f"  {i+1}. Pipeline alle {h:02d}:00 UTC → pubblica alle {publish[i] if i < len(publish) else '?'}:00 UTC"
                            for i, h in enumerate(trigger))
    await update.message.reply_text(
        f"📅 <b>Programma attuale</b>\n\n"
        f"📹 Video al giorno: {vpd}\n"
        f"✅ Prodotti oggi: {done}/{vpd}\n"
        f"🤖 Auto-scheduling: {'ON' if auto else 'OFF'}\n\n"
        f"{trigger_str}",
        parse_mode="HTML"
    )


async def cmd_prossimi(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    queue = state.get("topic_queue", [])
    vpd = state.get("videos_per_day", 1)
    now = datetime.now(timezone.utc)
    done = state.get("runs_today", {}).get(now.strftime("%Y-%m-%d"), 0)
    remaining = max(0, vpd - done)
    trigger_dt, publish_dt, idx = _next_schedule(state)
    next_topic = queue[0] if queue else "generato automaticamente"
    if trigger_dt is None:
        await update.message.reply_text("Nessun orario configurato.")
        return
    await update.message.reply_text(
        "⏭️ <b>Prossimi eventi</b>\n\n"
        f"🎬 Prossima pipeline: {trigger_dt.strftime('%d/%m/%Y %H:%M UTC')}\n"
        f"📅 Prossima pubblicazione: {publish_dt.strftime('%d/%m/%Y %H:%M UTC')}\n"
        f"📹 Video rimasti oggi: {remaining}/{vpd}\n"
        f"📌 Prossimo topic: <i>{html.escape(next_topic)}</i>",
        parse_mode="HTML",
    )


async def cmd_setpubblica(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text(
            "Uso: /setpubblica &lt;ora1&gt; [ora2 ...]\n"
            "Esempio: /setpubblica 14 → 1 video alle 14:00 UTC\n"
            "Esempio: /setpubblica 12 20 → 1° video alle 12:00, 2° alle 20:00 UTC\n\n"
            "Il trigger di produzione viene calcolato automaticamente 3 ore prima di ciascun orario.",
            parse_mode="HTML"
        )
        return
    try:
        ore = [int(a) for a in ctx.args]
        if any(not 0 <= o <= 23 for o in ore):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Ore non valide. Usa numeri tra 0 e 23.")
        return
    ore = sorted(set(ore))
    state = _load_state()
    state["publish_hours_utc"] = ore
    # cancella trigger_hours_utc espliciti: la produzione deriva sempre dalla pubblicazione
    state.pop("trigger_hours_utc", None)
    _save_state(state)
    trigger_ore = [(o - 3) % 24 for o in ore]
    lines = [f"  Video {i+1}: produzione alle <b>{t:02d}:00</b>, pubblicazione alle <b>{p:02d}:00</b> UTC"
             for i, (t, p) in enumerate(zip(trigger_ore, ore))]
    await update.message.reply_text(
        "✅ Orari aggiornati:\n" + "\n".join(lines),
        parse_mode="HTML"
    )


async def cmd_deltopic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    queue = state.get("topic_queue", [])

    if not queue:
        await update.message.reply_text("📋 Coda già vuota.")
        return

    if not ctx.args:
        await update.message.reply_text(
            "Uso: /deltopic <numero>\n\n"
            "Usa /coda per vedere i numeri."
        )
        return

    try:
        idx = int(ctx.args[0]) - 1
        if idx < 0 or idx >= len(queue):
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"Numero non valido. La coda ha {len(queue)} topic.")
        return

    rimosso = queue.pop(idx)
    state["topic_queue"] = queue
    _save_state(state)

    await update.message.reply_text(
        f"🗑 <b>Topic rimosso:</b>\n<i>{rimosso}</i>\n\n"
        f"Topic rimanenti in coda: {len(queue)}",
        parse_mode="HTML"
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.message.chat_id)
    state = _load_state()
    if "chat_history" in state and chat_id in state["chat_history"]:
        state["chat_history"][chat_id] = []
        _save_state(state)
    await update.message.reply_text(
        "🔄 <b>Contesto resettato.</b>\nL'AI non ricorda i messaggi precedenti di questa chat.\n"
        "La memoria lungo termine (<code>/memoria</code>) è invece intatta.",
        parse_mode="HTML"
    )


async def cmd_memoria(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.memoria import lista
    memories = lista()
    if not memories:
        await update.message.reply_text("🧠 Memoria vuota.")
        return
    righe = "\n".join(f"{i+1}. {m['testo']} <i>({m['data']})</i>" for i, m in enumerate(memories))
    await update.message.reply_text(f"🧠 <b>Memoria lungo termine:</b>\n\n{righe}", parse_mode="HTML")


async def cmd_dimentica(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.memoria import rimuovi, svuota, lista
    if ctx.args and ctx.args[0].lower() == "tutto":
        svuota()
        await update.message.reply_text("🗑 Memoria completamente svuotata.")
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /dimentica <numero> oppure /dimentica tutto\nUsa /memoria per vedere i numeri.")
        return
    try:
        idx = int(ctx.args[0]) - 1
        rimossa = rimuovi(idx)
        if rimossa:
            await update.message.reply_text(f"🗑 Rimosso: <i>{rimossa}</i>", parse_mode="HTML")
        else:
            await update.message.reply_text("Numero non valido.")
    except ValueError:
        await update.message.reply_text("Usa un numero. Es: /dimentica 2")


def _run_canale(fn, *args, **kwargs):
    from moduli.canale import (
        info_canale, aggiorna_canale, lista_video, lista_playlist,
        crea_playlist, lista_commenti, rispondi_commento, elimina_commento,
    )
    funcs = {
        "info_canale": info_canale, "aggiorna_canale": aggiorna_canale,
        "lista_video": lista_video, "lista_playlist": lista_playlist,
        "crea_playlist": crea_playlist, "lista_commenti": lista_commenti,
        "rispondi_commento": rispondi_commento, "elimina_commento": elimina_commento,
    }
    return funcs[fn](*args, **kwargs)


async def cmd_canale(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Recupero info canale...")
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _run_canale, "info_canale")
        msg = (
            f"📺 <b>{info['title']}</b>\n\n"
            f"👥 Iscritti: {info['subscribers']:,}\n"
            f"👁 Visualizzazioni: {info['views']:,}\n"
            f"📹 Video: {info['video_count']}\n"
            f"🌍 Paese: {info['country']}\n\n"
            f"📝 <b>Descrizione:</b>\n{info['description'][:300] or '—'}\n\n"
            f"🔑 <b>Keyword:</b> {info['keywords'][:200] or '—'}"
        )
    except Exception as e:
        msg = f"❌ Errore: {e}"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_setdesc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    desc = " ".join(ctx.args).strip() if ctx.args else ""
    if not desc:
        await update.message.reply_text("Uso: /setdesc <nuova descrizione>")
        return
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: _run_canale("aggiorna_canale", description=desc))
        await update.message.reply_text("✅ Descrizione canale aggiornata.")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def cmd_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Recupero video...")
    loop = asyncio.get_event_loop()
    try:
        videos = await loop.run_in_executor(None, _run_canale, "lista_video")
        if not videos:
            await update.message.reply_text("Nessun video trovato.")
            return
        lines = [f"📹 <b>Ultimi video:</b>"]
        for v in videos:
            lines.append(f"▪️ <a href='https://youtu.be/{v['video_id']}'>{v['title'][:50]}</a> — {v['published']}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def cmd_playlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Recupero playlist...")
    loop = asyncio.get_event_loop()
    try:
        playlists = await loop.run_in_executor(None, _run_canale, "lista_playlist")
        if not playlists:
            await update.message.reply_text("Nessuna playlist trovata.")
            return
        lines = ["📋 <b>Playlist:</b>"]
        for p in playlists:
            lines.append(f"▪️ {p['title']} ({p['count']} video) — <code>{p['id']}</code>")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def cmd_nuovaplaylist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    nome = " ".join(ctx.args).strip() if ctx.args else ""
    if not nome:
        await update.message.reply_text("Uso: /nuovaplaylist <nome>")
        return
    loop = asyncio.get_event_loop()
    try:
        pid = await loop.run_in_executor(None, lambda: _run_canale("crea_playlist", nome))
        await update.message.reply_text(f"✅ Playlist <b>{nome}</b> creata.\nID: <code>{pid}</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def cmd_commenti(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    video_id = ctx.args[0] if ctx.args else ""
    if not video_id:
        await update.message.reply_text("Uso: /commenti <videoId>")
        return
    loop = asyncio.get_event_loop()
    try:
        commenti = await loop.run_in_executor(None, lambda: _run_canale("lista_commenti", video_id))
        if not commenti:
            await update.message.reply_text("Nessun commento trovato.")
            return
        lines = [f"💬 <b>Commenti:</b>"]
        for c in commenti:
            lines.append(f"<b>{c['author']}</b> (❤️{c['likes']})\n{c['text'][:150]}\n<code>{c['id']}</code>")
        await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def handle_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    caption = (msg.caption or "").strip().lower()

    # determina scope
    state_for_scope = _load_state()
    queue_for_scope = state_for_scope.get("topic_queue", [])
    if not caption or "next" in caption or "prossimo" in caption:
        scope = "next"
    elif "all" in caption or "tutti" in caption or "sempre" in caption:
        scope = "all"
    else:
        # cerca numero nella didascalia → usa il topic corrispondente
        import re as _re
        num_match = _re.search(r'\d+', caption)
        if num_match:
            idx = int(num_match.group()) - 1  # 1-based → 0-based
            if 0 <= idx < len(queue_for_scope):
                scope = queue_for_scope[idx]
            else:
                await msg.reply_text(f"Numero topic non valido. Hai {len(queue_for_scope)} topic in coda.")
                return
        else:
            scope = caption  # testo libero come topic parziale

    # determina tipo e file
    if msg.photo:
        media_type = "thumbnail"
        file_obj = msg.photo[-1]  # massima risoluzione
        folder = "assets/custom/thumbnails"
        ext = ".jpg"
    elif msg.video or (msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video")):
        media_type = "video"
        file_obj = msg.video or msg.document
        folder = "assets/custom/clips"
        ext = ".mp4"
    elif msg.audio or msg.voice or (msg.document and msg.document.mime_type and msg.document.mime_type.startswith("audio")):
        media_type = "audio"
        file_obj = msg.audio or msg.voice or msg.document
        folder = "assets/custom/audio"
        mime = getattr(file_obj, "mime_type", "audio/mpeg")
        ext = ".ogg" if msg.voice else (".mp3" if "mpeg" in mime or "mp3" in mime else ".m4a" if "m4a" in mime or "mp4" in mime else ".ogg")
    else:
        await msg.reply_text("Formato non supportato. Invia foto, video (MP4) o audio (MP3/M4A).")
        return

    os.makedirs(folder, exist_ok=True)
    file_id = file_obj.file_id
    fname = f"{file_id[:16]}{ext}"
    dest = os.path.join(folder, fname)

    await msg.reply_text(f"Ricevuto {media_type} — salvataggio in corso...")
    tg_file = await ctx.bot.get_file(file_id)
    await tg_file.download_to_drive(dest)

    state = _load_state()
    custom = state.setdefault("custom_media", {"clips": [], "audio": [], "thumbnails": []})
    key = {"video": "clips", "audio": "audio", "thumbnail": "thumbnails"}[media_type]
    custom[key] = [e for e in custom.get(key, []) if e.get("file_id") != file_id]
    custom[key].append({"path": dest, "scope": scope, "file_id": file_id})
    _save_state(state)

    scope_label = {"next": "solo nel prossimo video", "all": "in tutti i video futuri"}.get(scope, f"nel video: '{scope[:60]}'")
    type_label = {"video": "Clip video", "audio": "Audio", "thumbnail": "Copertina"}[media_type]

    await msg.reply_text(
        f"✅ {type_label} salvata e verra usata {scope_label}.\n"
        f"Percorso: <code>{dest}</code>\n\n"
        f"Didascalia: vuota=prossimo, 'all'=tutti, numero=topic N della coda.",
        parse_mode="HTML"
    )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return

    chat_id = str(update.message.chat_id)
    await update.message.chat.send_action("typing")
    loop = asyncio.get_event_loop()

    state = _load_state()
    history = _get_history(state, chat_id)

    if _is_preference_list_request(text):
        from moduli.preferenze import formato_html
        await update.message.reply_text(formato_html(), parse_mode="HTML")
        return

    from moduli.preferenze import aggiorna_da_testo
    pref_updates = aggiorna_da_testo(text)
    if pref_updates and not any(k in text.lower() for k in _ACTION_KEYWORDS):
        await update.message.reply_text(_format_preference_updates(pref_updates), parse_mode="HTML")
        return

    future = loop.run_in_executor(None, _ask_ai, text, history, state)
    while not future.done():
        await asyncio.sleep(4)
        if not future.done():
            await update.message.chat.send_action("typing")

    reply, new_history = await future

    # esegui azioni embedded nella risposta
    clean_reply, added_topics, saved_memories, removed_memories, api_results = _execute_actions(reply, state, is_search=_needs_web_search(text))

    _save_history(state, chat_id, new_history)
    _save_state(state)

    msg = clean_reply or reply or "⚠️ Risposta vuota dal modello AI. Riprova."
    if len(msg) > 4096:
        for i in range(0, len(msg), 4096):
            await update.message.reply_text(msg[i:i+4096])
    else:
        await update.message.reply_text(msg)

    if added_topics:
        elenco = "\n".join(f"• {t}" for t in added_topics)
        await update.message.reply_text(
            f"✅ <b>Aggiunti {len(added_topics)} topic in coda:</b>\n{elenco}",
            parse_mode="HTML"
        )
    if saved_memories:
        elenco = "\n".join(f"• {m}" for m in saved_memories)
        await update.message.reply_text(
            f"🧠 <b>Memorizzato:</b>\n{elenco}",
            parse_mode="HTML"
        )
    if removed_memories:
        elenco = "\n".join(f"• {m}" for m in removed_memories)
        await update.message.reply_text(
            f"🗑 <b>Rimosso dalla memoria:</b>\n{elenco}",
            parse_mode="HTML"
        )
    for msg in api_results:
        await update.message.reply_text(msg, parse_mode="HTML")


def start_bot() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[Telegram] No token — bot disabled")
        return

    async def _run():
        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("recap", cmd_recap))
        app.add_handler(CommandHandler("preferenze", cmd_preferenze))
        app.add_handler(CommandHandler("setpref", cmd_setpref))
        app.add_handler(CommandHandler("forza", cmd_forza))
        app.add_handler(CommandHandler("forzaora", cmd_forzaora))
        app.add_handler(CommandHandler("skip", cmd_skip))
        app.add_handler(CommandHandler("abort", cmd_abort))
        app.add_handler(CommandHandler("coda", cmd_coda))
        app.add_handler(CommandHandler("topic", cmd_topic))
        app.add_handler(CommandHandler("deltopic", cmd_deltopic))
        app.add_handler(CommandHandler("setvideogiorno", cmd_setvideogiorno))
        app.add_handler(CommandHandler("autoscheduling", cmd_autoscheduling))
        app.add_handler(CommandHandler("orari", cmd_orari))
        app.add_handler(CommandHandler("prossimi", cmd_prossimi))
        app.add_handler(CommandHandler("setpubblica", cmd_setpubblica))
        app.add_handler(CommandHandler("canale", cmd_canale))
        app.add_handler(CommandHandler("setdesc", cmd_setdesc))
        app.add_handler(CommandHandler("video", cmd_video))
        app.add_handler(CommandHandler("playlist", cmd_playlist))
        app.add_handler(CommandHandler("nuovaplaylist", cmd_nuovaplaylist))
        app.add_handler(CommandHandler("commenti", cmd_commenti))
        app.add_handler(CommandHandler("reset", cmd_reset))
        app.add_handler(CommandHandler("memoria", cmd_memoria))
        app.add_handler(CommandHandler("dimentica", cmd_dimentica))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(MessageHandler(filters.VIDEO | filters.AUDIO | filters.VOICE | filters.PHOTO | filters.Document.VIDEO | filters.Document.AUDIO, handle_media))

        await app.initialize()
        await app.bot.set_my_commands([
            ("start",          "Mostra tutti i comandi"),
            ("status",         "Stato attuale dell'agent"),
            ("recap",          "Analytics ultimi video"),
            ("forza",          "Lancia la pipeline subito"),
            ("forzaora",       "Pubblica subito senza programmazione"),
            ("skip",           "Salta il video di oggi"),
            ("abort",          "Ferma la pipeline in corso"),
            ("orari",          "Programma attuale"),
            ("prossimi",       "Prossimo run e publish"),
            ("setvideogiorno", "Imposta quanti video al giorno"),
            ("setpubblica",    "Ora/e pubblicazione video (UTC)"),
            ("autoscheduling", "Orari automatici da analytics"),
            ("coda",           "Topic in coda"),
            ("topic",          "Aggiungi topic alla coda"),
            ("deltopic",       "Rimuovi topic dalla coda"),
            ("canale",         "Info e statistiche canale"),
            ("setdesc",        "Aggiorna descrizione canale"),
            ("video",          "Ultimi video pubblicati"),
            ("playlist",       "Playlist del canale"),
            ("nuovaplaylist",  "Crea nuova playlist"),
            ("commenti",       "Leggi commenti di un video"),
            ("reset",          "Resetta il contesto conversazione"),
            ("memoria",        "Vedi memoria lungo termine"),
            ("dimentica",      "Rimuovi un ricordo"),
        ])
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print("[Telegram] Bot polling started")

        while True:
            await asyncio.sleep(3600)

    def _thread():
        asyncio.run(_run())

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
