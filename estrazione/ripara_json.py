"""Ripara i JSON non validi restituiti dal modello (virgole mancanti, testo tagliato...) usando la risposta grezza."""
import json, re, sys
from json_repair import repair_json

def ripara(r):
    if isinstance(r.get("pred"), dict) or not r.get("grezzo"): return r
    m = re.search(r"\{.*", r["grezzo"], re.S)
    try:
        p = json.loads(repair_json(m.group())) if m else None
        if isinstance(p, dict): r["pred"], r["json_riparato"] = p, True
    except Exception:
        pass
    return r

if __name__ == "__main__":
    with open(sys.argv[2], "w") as f:
        for l in open(sys.argv[1]): f.write(json.dumps(ripara(json.loads(l)), ensure_ascii=False) + "\n")
