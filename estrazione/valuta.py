"""Confronta le predizioni (una per scheda, JSON) con la verità del generatore.

Uso: python valuta.py --verita cartella_json --pred predizioni.jsonl [--out report.json]
predizioni.jsonl: una riga per scheda {"doc_id": ..., "pred": {...} | null, "secondi": .., "costo_usd": ..}
"""
import argparse, glob, json, os, statistics as st
from collections import defaultdict
from schema import STAMPATI, A_MANO, RIGA, uguali, somiglianza_note


def confronta(v, p):
    """Ritorna {campo: bool} per ogni campo atteso + somiglianza note."""
    out = {}
    for c in STAMPATI + A_MANO:
        out[c] = uguali(p.get(c), v.get(c), c)
    rv, rp = v.get("righe", []), p.get("righe") or []
    out["n_righe"] = len(rv) == len(rp)
    for i, r in enumerate(rv):
        q = rp[i] if i < len(rp) and isinstance(rp[i], dict) else {}
        for c in RIGA:
            out[f"righe.{c}"] = out.get(f"righe.{c}", []) + [uguali(q.get(c), r.get(c), c)]
    out["note_sim"] = somiglianza_note(p.get("note"), v.get("note"))
    return out


def incerti(p):
    """Campi segnalati: 'seriale', 'righe[1].codice' (una cella) o 'righe' (tutta la tabella)."""
    return {str(x).strip().replace(" ", "") for x in (p.get("campi_incerti") or [])}


def segnalato(inc, campo, i=None):
    if i is None: return campo in inc
    c = campo.split(".")[1]
    return "righe" in inc or f"righe[{i}].{c}" in inc or f"righe[{i}]" in inc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verita", required=True); ap.add_argument("--pred", required=True); ap.add_argument("--out")
    a = ap.parse_args()
    ver = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(a.verita, "*.json"))}
    preds = [json.loads(l) for l in open(a.pred) if l.strip()]
    acc, note, tempi, costi, perfette, falliti = defaultdict(list), [], [], [], 0, 0
    segnalati = {"errore_segnalato": 0, "errore_non_segnalato": 0, "ok_segnalato": 0}
    for r in preds:
        v, p = ver.get(r["doc_id"]), r.get("pred")
        if v is None: continue
        tempi.append(r.get("secondi") or 0); costi.append(r.get("costo_usd") or 0)
        if not isinstance(p, dict):
            falliti += 1; p = {}
        c = confronta(v, p); inc = incerti(p)
        if r.get("pred") is None or not isinstance(r.get("pred"), dict):   # JSON non valido = tutto sbagliato
            c = {k: ([False] * len(x) if isinstance(x, list) else (0.0 if k == "note_sim" else False)) for k, x in c.items()}
        tutto = True
        for k, x in c.items():
            if k == "note_sim": note.append(x); continue
            vals = x if isinstance(x, list) else [x]
            acc[k] += vals; tutto &= all(vals)
            for j, ok in enumerate(vals):
                flag = segnalato(inc, k, j if isinstance(x, list) else None)
                if not ok: segnalati["errore_segnalato" if flag else "errore_non_segnalato"] += 1
                elif flag: segnalati["ok_segnalato"] += 1
        perfette += tutto
    n = len([r for r in preds if r["doc_id"] in ver])
    rep = {"schede": n, "json_non_validi": falliti,
           "accuratezza_campi": {k: round(sum(v) / len(v), 3) for k, v in sorted(acc.items())},
           "accuratezza_stampati": round(st.mean(x for k in STAMPATI for x in acc[k]), 3),
           "accuratezza_a_mano": round(st.mean([x for k in A_MANO for x in acc[k]] + [x for k in acc if k.startswith("righe.") for x in acc[k]]), 3),
           "note_parole_ritrovate": round(st.mean(note), 3) if note else None,
           "schede_perfette": round(perfette / max(n, 1), 3),
           "secondi_per_scheda": round(st.mean(tempi), 1) if tempi else None,
           "costo_per_scheda_usd": round(st.mean(costi), 5) if costi else None,
           "auto_segnalazione": segnalati}
    e = segnalati["errore_segnalato"] + segnalati["errore_non_segnalato"]
    rep["errori_intercettati"] = round(segnalati["errore_segnalato"] / e, 3) if e else None
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if a.out: json.dump(rep, open(a.out, "w"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
