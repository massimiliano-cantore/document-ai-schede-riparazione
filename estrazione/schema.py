"""Schema dei dati da estrarre, normalizzazione e confronto con la verità.

La verità (JSON del generatore) ha già "idem" risolto: se in tabella c'è "n" o le virgolette,
il valore atteso è quello della riga sopra. Il modello deve fare lo stesso.
"""
import re, unicodedata

STAMPATI = ["riparazione_n", "data", "cliente", "articolo", "pezzi", "ricevuto_il", "ddt_n", "ddt_del"]
A_MANO = ["prodotto_il", "seriale", "aperta_manomessa", "tempo_riparazione_min", "firmware", "eseguito_il"]
RIGA = ["codice", "descrizione", "intervento", "causa", "pz"]

VUOTI = {"", "/", "-", "--", "—", "N/A", "NA", "NONE", "NULL", "NESSUNO"}


def norm(v, campo=""):
    """Porta un valore a una forma confrontabile (maiuscolo, spazi, date, numeri)."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else v
    s = unicodedata.normalize("NFKC", str(v)).upper().strip()
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    if s in VUOTI:
        return None
    if campo in ("pezzi", "pz", "tempo_riparazione_min"):
        m = re.search(r"\d+", s)
        return int(m.group()) if m else None
    if campo in ("data", "ricevuto_il", "ddt_del", "prodotto_il", "eseguito_il"):
        m = re.match(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?$", s)
        if m:
            g, mm, a = m.groups()
            a = ("20" + a if a and len(a) == 2 else a)
            return f"{int(g):02d}/{int(mm):02d}" + (f"/{a}" if a else "")
    if campo == "aperta_manomessa":
        return {"SI": True, "SÌ": True, "TRUE": True, "NO": False, "FALSE": False}.get(s)
    if campo in ("codice", "seriale", "firmware", "articolo"):
        s = s.replace(" ", "")
    return s


def uguali(a, b, campo):
    return norm(a, campo) == norm(b, campo)


def parole(s):
    return re.findall(r"[A-Z0-9']+", (norm(s) or "")) if s else []


def somiglianza_note(pred, vero):
    """Quota di parole della nota vera ritrovate, nello stesso ordine (0-1)."""
    import difflib
    a, b = parole(vero), parole(pred)
    if not a:
        return 1.0 if not b else 0.0
    m = difflib.SequenceMatcher(None, a, b)
    return sum(t.size for t in m.get_matching_blocks()) / len(a)
