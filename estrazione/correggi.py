"""Correzione delle predizioni con le regole del modulo e il catalogo ricambi.

Nel mondo reale il catalogo (codici e descrizioni dei componenti) esiste già nel gestionale:
usarlo trasforma una lettura "quasi giusta" (CAVC10) nel codice vero (CAV2210), e la distanza
dalla voce di catalogo diventa un indice di confidenza per segnalare i casi dubbi.
"""
import difflib, json, os, re

CAT = json.load(open(os.path.join(os.path.dirname(__file__), "catalogo.json")))
IDEM = {"N", "U", "II", "\"", "''", "//", "\u201d", "IDEM", "ID", "N/A", "N (N)", "U (U)"}


def _n(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def sim(a, b):
    return difflib.SequenceMatcher(None, _n(a), _n(b)).ratio()


def _piu_vicino(x, voci):
    if not x: return None, 0.0
    best = max(voci, key=lambda v: sim(x, v))
    return best, sim(x, best)


def correggi(p, soglia=0.5):
    """Ritorna (predizione corretta, lista campi incerti aggiunti)."""
    if not isinstance(p, dict): return p, []
    p = json.loads(json.dumps(p)); incerti = set(p.get("campi_incerti") or [])
    prec = {}
    for i, r in enumerate(p.get("righe") or []):
        if not isinstance(r, dict): continue
        iv = str(r.get("intervento") or "").strip()
        m = re.match(r"^(.*?)\s*\((.*?)\)?\s*$", iv)            # "SOSTITUZIONE (ROTTO)" -> intervento + causa
        if m:
            iv = m.group(1).strip()
            if not r.get("causa"): r["causa"] = m.group(2).strip()
        for campo, val in (("intervento", iv), ("causa", r.get("causa"))):
            v = str(val or "").strip()
            if v.upper() in IDEM: v = prec.get(campo) or ""            # idem = riga sopra
            r[campo] = v or None
        # codice + descrizione: voce di catalogo più coerente con entrambe le letture
        voce = max(CAT["componenti"], key=lambda c: sim(r.get("codice"), c["codice"]) + sim(r.get("descrizione"), c["descrizione"]))
        s = (sim(r.get("codice"), voce["codice"]) + sim(r.get("descrizione"), voce["descrizione"])) / 2
        if s >= soglia:
            r["codice"], r["descrizione"] = voce["codice"], voce["descrizione"]
        if s < 0.8: incerti.add(f"righe[{i}].codice")
        for campo, lista in (("intervento", CAT["interventi"]), ("causa", CAT["cause"])):
            if r.get(campo):
                v, s2 = _piu_vicino(r[campo], lista)
                if s2 >= soglia: r[campo] = v
                if s2 < 0.8: incerti.add(f"righe[{i}].{campo}")
        prec = {"intervento": r.get("intervento"), "causa": r.get("causa")}
    p["campi_incerti"] = sorted(incerti)
    return p, sorted(incerti)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("inp"); ap.add_argument("out"); a = ap.parse_args()
    with open(a.out, "w") as f:
        for l in open(a.inp):
            r = json.loads(l); r["pred"], _ = correggi(r.get("pred")); f.write(json.dumps(r, ensure_ascii=False) + "\n")
