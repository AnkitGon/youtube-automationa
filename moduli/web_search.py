import time
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS


def cerca_notizie(query: str, max_results: int = 5) -> str:
    """Cerca su DuckDuckGo e restituisce un blocco testo da iniettare nel prompt."""
    # forza ricerca in inglese per migliore copertura e meno rate limit
    search_query = f"{query} 2025 2026"
    for attempt in range(3):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(search_query, max_results=max_results, region="en-us"))
            if results:
                lines = []
                for r in results:
                    title = r.get("title", "")
                    body  = r.get("body", "")
                    href  = r.get("href", "")
                    lines.append(f"- {title}: {body} ({href})")
                return "\n".join(lines)
        except Exception as e:
            err = str(e)
            if "Ratelimit" in err or "429" in err:
                time.sleep(3 * (attempt + 1))
                continue
            print(f"[WebSearch] Errore: {e}", flush=True)
            return ""
    print("[WebSearch] Rate limit persistente, skip ricerca", flush=True)
    return ""
