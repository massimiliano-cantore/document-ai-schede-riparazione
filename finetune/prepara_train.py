"""Fine-tuning - prepara il dataset di addestramento dalle schede sintetiche generate.

Ogni esempio = 2 pagine (fronte/retro) ridotte a ~1,1 MP + la risposta attesa: il JSON nel formato del prompt.
Le schede di addestramento usano semi diversi da quelle di test (seed 1) e le 25 schede reali NON ci entrano mai.
Uso: python prepara_train.py <cartelle generate...> --out <cartella dataset>
"""
import argparse, glob, json, os
from PIL import Image

LATO = (896, 1267)          # ~1440 token visivi per pagina in Qwen2.5-VL: leggibile e sostenibile su una T4
CAMPI = ["riparazione_n", "data", "cliente", "articolo", "pezzi", "ricevuto_il", "ddt_n", "ddt_del", "prodotto_il",
         "seriale", "aperta_manomessa", "tempo_riparazione_min", "firmware", "righe", "note", "eseguito_il"]
RIGA = ["codice", "descrizione", "intervento", "causa", "pz"]


def risposta(v):
    """Verita' -> JSON di uscita, stesso formato chiesto dal prompt di estrazione."""
    r = {k: v.get(k) for k in CAMPI}
    r["righe"] = [{k: riga.get(k) for k in RIGA} for riga in v["righe"]]
    r["campi_incerti"] = []
    return json.dumps(r, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cartelle", nargs="+"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(f"{a.out}/pagine", exist_ok=True)
    n = 0
    with open(f"{a.out}/train.jsonl", "w") as f:
        for c in a.cartelle:
            tag = os.path.basename(c.rstrip("/"))
            for js in sorted(glob.glob(f"{c}/*.json")):
                d = os.path.basename(js)[:-5]
                nuovo = f"TRN-{tag}-{d[-5:]}"
                pagine = []
                for k in (1, 2):
                    im = Image.open(f"{c}/{d}_p{k}.png").convert("RGB").resize(LATO, Image.LANCZOS)
                    p = f"pagine/{nuovo}_p{k}.jpg"
                    im.save(f"{a.out}/{p}", quality=88)
                    pagine.append(p)
                f.write(json.dumps({"doc_id": nuovo, "pagine": pagine, "risposta": risposta(json.load(open(js)))},
                                   ensure_ascii=False) + "\n")
                n += 1
    print(n, "esempi in", a.out)


if __name__ == "__main__":
    main()
