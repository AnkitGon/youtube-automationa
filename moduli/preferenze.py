"""Preferenze stilistiche persistenti per i video."""
import html
import json
import os
import re

PREF_FILE = "preferenze_video.json"

DEFAULT_PREF = {
    "ritmo": "medio",              # lento / medio / veloce
    "tono_voce": "confident",      # confident / casual / dramatic / educational
    "lingua": "english",           # english / italian
    "stile_clip": "cinematic",     # cinematic / fast cuts / minimal / documentary
    "stile_thumbnail": "cinematic dramatic lighting, dark moody",
    "argomenti_preferiti": ["AI", "technology", "future tech"],
    "argomenti_evitare": [],
    "durata_target_minuti": 8,
    "musica_volume": 0.1,
    "note_libere": "",
}


def carica() -> dict:
    if os.path.exists(PREF_FILE):
        try:
            with open(PREF_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return {**DEFAULT_PREF, **data}
        except Exception:
            pass
    return DEFAULT_PREF.copy()


def salva(pref: dict) -> None:
    with open(PREF_FILE, "w", encoding="utf-8") as f:
        json.dump(pref, f, indent=2, ensure_ascii=False)


def _lista_da_testo(valore: str) -> list[str]:
    valore = re.sub(r"\s+(?:e|and)\s+", ",", valore, flags=re.IGNORECASE)
    return [v.strip(" .;:-\"'") for v in valore.split(",") if v.strip(" .;:-\"'")]


def _converti_valore(chiave: str, valore):
    default_val = DEFAULT_PREF[chiave]
    if isinstance(default_val, list):
        if isinstance(valore, list):
            return [str(v).strip() for v in valore if str(v).strip()]
        return _lista_da_testo(str(valore))
    if isinstance(default_val, int):
        match = re.search(r"\d+", str(valore))
        if not match:
            raise ValueError(f"Valore non valido per {chiave}")
        return int(match.group(0))
    if isinstance(default_val, float):
        raw = str(valore).replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", raw)
        if not match:
            raise ValueError(f"Valore non valido per {chiave}")
        return float(match.group(0))
    return str(valore).strip().strip('"').strip("'")


def aggiorna(chiave: str, valore) -> dict:
    pref = carica()
    pref[chiave] = _converti_valore(chiave, valore)
    salva(pref)
    return pref


def aggiorna_da_testo(testo: str) -> dict:
    """Aggiorna preferenze da frasi naturali e restituisce solo le modifiche."""
    pref = carica()
    original = testo.strip()
    t = original.lower()
    modifiche = {}

    def set_pref(chiave: str, valore, merge_list: bool = False) -> None:
        nuovo = _converti_valore(chiave, valore)
        if merge_list and isinstance(DEFAULT_PREF[chiave], list):
            esistenti = pref.get(chiave, [])
            nuovo = [*esistenti, *[v for v in nuovo if v not in esistenti]]
        pref[chiave] = nuovo
        modifiche[chiave] = nuovo

    alias_espliciti = {
        "ritmo": ("ritmo",),
        "tono_voce": ("tono_voce", "tono voce"),
        "lingua": ("lingua", "language"),
        "stile_clip": ("stile_clip", "stile clip"),
        "stile_thumbnail": ("stile_thumbnail", "stile thumbnail"),
        "argomenti_preferiti": ("argomenti_preferiti", "argomenti preferiti"),
        "argomenti_evitare": ("argomenti_evitare", "argomenti evitare"),
        "durata_target_minuti": ("durata_target_minuti", "durata target minuti"),
        "musica_volume": ("musica_volume", "musica volume", "volume musica"),
        "note_libere": ("note_libere", "note libere"),
    }
    for chiave, aliases in alias_espliciti.items():
        for alias in aliases:
            match = re.search(rf"\b{re.escape(alias)}\b\s*(?:=|:)?\s+(.+)", original, re.IGNORECASE)
            if match:
                set_pref(chiave, match.group(1))
                break

    if re.search(r"\b(lento|medio|veloce|fast)\b", t) and re.search(r"\b(ritmo|pace|taglio|montaggio|video)\b", t):
        if "veloce" in t or "fast" in t:
            set_pref("ritmo", "veloce")
        elif "lento" in t:
            set_pref("ritmo", "lento")
        elif "medio" in t:
            set_pref("ritmo", "medio")

    tono_match = re.search(r"\b(?:tono(?:_voce|\s+voce)?|voce)\b\s*(?:=|:|a|in|piu|piu'|più)?\s*(confident|casual|dramatic|educational|drammatico|educativo)", t)
    if tono_match:
        value = tono_match.group(1)
        value = {"drammatico": "dramatic", "educativo": "educational"}.get(value, value)
        set_pref("tono_voce", value)

    lingua_match = re.search(r"\b(?:lingua|language)\b\s*(?:=|:|in|a)?\s*(english|italian|inglese|italiano)", t)
    if lingua_match:
        value = lingua_match.group(1)
        value = {"inglese": "english", "italiano": "italian"}.get(value, value)
        set_pref("lingua", value)

    clip_match = re.search(r"\b(?:stile\s+clip|clip|montaggio)\b\s*(?:=|:|in|a)?\s*(cinematic|fast cuts|minimal|documentary|documentario)", t)
    if clip_match:
        value = clip_match.group(1)
        value = {"documentario": "documentary"}.get(value, value)
        set_pref("stile_clip", value)

    durata_match = re.search(r"\b(?:durata|lunghezza|video\s+da)\b[^\d]{0,20}(\d+)\s*(?:min|minuti|minutes)?", t)
    if durata_match:
        set_pref("durata_target_minuti", durata_match.group(1))

    volume_match = re.search(r"\b(?:volume\s+musica|musica\s+volume)\b[^\d]{0,20}(\d+(?:[\.,]\d+)?)", t)
    if volume_match:
        set_pref("musica_volume", volume_match.group(1))

    evita_match = re.search(
        r"\b(?:evita|argomenti\s+da\s+evitare|non\s+(?:parlare|trattare)\s+di|non\s+voglio\s+(?:video|argomenti|contenuti)?\s*(?:su|di|che\s+parlino\s+di))\b\s*(?:parlare\s+di\s*)?(.+)",
        original,
        re.IGNORECASE,
    )
    if evita_match:
        valore = re.sub(r"^(?:argomenti\s+)?(?:come\s+)?", "", evita_match.group(1).strip(), flags=re.IGNORECASE)
        set_pref("argomenti_evitare", valore, merge_list=True)

    preferiti_match = re.search(r"\b(?:argomenti\s+preferiti|parla\s+di|voglio\s+argomenti\s+su)\b\s*(.+)", original, re.IGNORECASE)
    if preferiti_match and "non " not in t:
        set_pref("argomenti_preferiti", preferiti_match.group(1), merge_list=True)

    thumb_match = re.search(r"\b(?:stile\s+thumbnail|thumbnail|copertina)\b\s*(?:=|:|con|in|stile)?\s*(.+)", original, re.IGNORECASE)
    if thumb_match:
        value = thumb_match.group(1).strip(" .")
        if value:
            set_pref("stile_thumbnail", value)

    note_match = re.search(r"\b(?:nota|ricorda\s+per\s+i\s+video|preferenza\s+generale)\b\s*[:\-]?\s*(.+)", original, re.IGNORECASE)
    if note_match:
        set_pref("note_libere", note_match.group(1))

    if modifiche:
        salva(pref)
    return modifiche


def formato_html() -> str:
    pref = carica()
    lines = ["⚙️ <b>Preferenze video attuali:</b>\n"]
    for k, v in pref.items():
        val = ", ".join(v) if isinstance(v, list) else str(v)
        lines.append(f"<b>{html.escape(k)}</b>: {html.escape(val or '-')}")
    lines.append("\nPuoi scrivere in modo naturale, per esempio:")
    lines.append("<code>metti ritmo veloce</code>")
    lines.append("<code>evita crypto e web3</code>")
    lines.append("<code>thumbnail con colori vivi e stile energico</code>")
    return "\n".join(lines)


def come_contesto() -> str:
    pref = carica()
    return (
        "[PREFERENZE UTENTE DEL CANALE]\n"
        f"- Ritmo: {pref['ritmo']}\n"
        f"- Tono voce: {pref['tono_voce']}\n"
        f"- Lingua: {pref['lingua']}\n"
        f"- Stile clip: {pref['stile_clip']}\n"
        f"- Stile thumbnail: {pref['stile_thumbnail']}\n"
        f"- Argomenti preferiti: {', '.join(pref['argomenti_preferiti'])}\n"
        f"- Argomenti da evitare: {', '.join(pref['argomenti_evitare']) or 'nessuno'}\n"
        f"- Durata target: {pref['durata_target_minuti']} minuti\n"
        f"- Note: {pref['note_libere'] or 'nessuna'}"
    )
