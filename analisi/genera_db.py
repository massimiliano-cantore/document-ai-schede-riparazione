"""Tappa 3 - genera un database SQLite SINTETICO dei resi di KYROS ACCESS (azienda fittizia).

Le distribuzioni (stagionalita', concentrazione clienti/articoli, tempi, esiti, errori di
battitura) imitano la forma di un archivio reale, ma ogni riga e' inventata.
Uso:  python analisi/genera_db.py  ->  analisi/dati/resi_kyros.db
"""
import sqlite3, string, sys
from datetime import date, timedelta
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generator"))
from genera_schede import ARTICOLI, COMPONENTI, NOTE_DIAGNOSI  # stesso dominio della tappa 2

OUT = Path(__file__).parent / "dati" / "resi_kyros.db"
rng = np.random.default_rng(42)

SCHEMA = """
CREATE TABLE clienti  (id INTEGER PRIMARY KEY, nome TEXT, provincia TEXT, tipo TEXT);
CREATE TABLE articoli (id INTEGER PRIMARY KEY, codice TEXT UNIQUE, famiglia TEXT, lancio INTEGER);
CREATE TABLE rientri (
  id INTEGER PRIMARY KEY, riparazione_numero TEXT, anno INTEGER, scheda_progressiva INTEGER,
  cliente_id INTEGER REFERENCES clienti(id), articolo_id INTEGER REFERENCES articoli(id),
  quantita INTEGER, ddt_numero TEXT, ddt_data DATE, ricevuto_il DATE,
  scheda_consegnata DATE, data_chiusura DATE, operazione TEXT, in_garanzia INTEGER, note TEXT);
CREATE TABLE pezzi_intervento (
  id INTEGER PRIMARY KEY, rientro_id INTEGER REFERENCES rientri(id),
  codice TEXT, descrizione TEXT, intervento TEXT, quantita INTEGER);
"""

PROV = ["MO", "BO", "RE", "PR", "VR", "MN", "MI", "BS", "PD", "VI", "FI", "TO", "RM", "AN", "TV"]
TIPI = ["installatore", "installatore", "installatore", "distributore", "impresa edile", "hotel", "ente pubblico"]
SILL = ["NOVA", "TEC", "EDIL", "SICUR", "DOMO", "ALFA", "BETA", "PORTA", "LOG", "ELETTR", "SERV", "IMP", "CASA", "TERM", "VAL"]
SUFF = ["SRL", "SNC", "SPA", "SAS", "IMPIANTI", "SERVIZI", "SISTEMI", "GROUP"]


def nome_cliente():
    return f"{rng.choice(SILL)}{rng.choice(SILL)} {rng.choice(SUFF)}"


def main():
    OUT.parent.mkdir(exist_ok=True)
    OUT.unlink(missing_ok=True)
    db = sqlite3.connect(OUT)
    db.executescript(SCHEMA)

    # clienti: ~1200 con concentrazione forte (Zipf) -> top10 ~ 1/4 dei resi
    nomi = sorted({nome_cliente() for _ in range(3000)})[:1200]
    rng.shuffle(nomi)
    db.executemany("INSERT INTO clienti VALUES (?,?,?,?)",
                   [(i + 1, n, str(rng.choice(PROV)), str(rng.choice(TIPI))) for i, n in enumerate(nomi)])
    p_cli = 1 / np.arange(1, 1201) ** 0.9; p_cli /= p_cli.sum()

    # articoli: i 10 della tappa 2 + varianti -> ~300 codici, famiglie con tassi di guasto diversi
    arts = []
    for base, fam in ARTICOLI.items():
        for v in range(30):
            arts.append((f"{base}{'' if v == 0 else '-' + str(v).zfill(2)}", fam, int(rng.integers(2014, 2025))))
    db.executemany("INSERT INTO articoli VALUES (?,?,?,?)", [(i + 1, *a) for i, a in enumerate(arts)])
    peso_fam = {"serratura": 3.0, "cilindro": 1.5, "centralina": 1.2, "lettore": 1.0, "tastiera": .6}
    p_art = np.array([peso_fam[f] / (1 + v) ** 1.1 for (_, f, _), v in zip(arts, [i % 30 for i in range(len(arts))])])
    p_art /= p_art.sum()

    stag = np.array([1.35, 1.2, 1.0, .85, 1.1, .9, 1.0, .25, 1.15, 1.0, .95, .6])  # agosto chiuso, dicembre corto
    volumi = {2022: 1270, 2023: 1640, 2024: 1820, 2025: 1650, 2026: 1250}
    oper = (["spedito"] * 73 + ["mpf"] * 8 + ["rottamato"] * 3 + ["sostituito"] * 2 + ["reso a cliente"])
    refusi = {"spedito": ["speditp", "SPEDITO ", "spedita"], "rottamato": ["rottamata", "rottamare"]}

    rientri, pezzi, rid, pid = [], [], 0, 0
    for anno, n in volumi.items():
        mesi_attivi = 12 if anno < 2026 else 9           # il 2026 e' parziale (fino a settembre)
        pm = stag[:mesi_attivi] / stag[:mesi_attivi].sum()
        n = n if anno < 2026 else int(n * .75)
        cont = 0
        while cont < n:
            mese = int(rng.choice(np.arange(1, mesi_attivi + 1), p=pm))
            ric = date(anno, mese, int(rng.integers(1, 29)))
            ddt_data = ric - timedelta(days=int(rng.gamma(1.5, 2.5)))
            cli = int(rng.choice(1200, p=p_cli)) + 1
            n_righe = 1 if rng.random() < .62 else int(rng.integers(2, 6))   # una riparazione = uno o piu' articoli
            num = f"{cont // 20 + 1:02d}/{mese:02d}"
            ddt = f"{int(rng.integers(1, 3000))}/{anno}"
            for scheda in range(1, n_righe + 1):     # una scheda per pezzo, numerate 1..n
                rid += 1; cont += 1
                a = int(rng.choice(len(arts), p=p_art))
                art_id, fam, lancio = a + 1, arts[a][1], arts[a][2]
                eta = anno - lancio
                op = str(rng.choice(oper))
                if fam == "serratura" and eta > 7 and rng.random() < .25: op = "rottamato"
                consegna = ric + timedelta(days=int(rng.gamma(1.4, 3)))
                durata = rng.lognormal(2.2 + (.5 if op == "mpf" else 0) + (.3 if fam == "centralina" else 0), .8)
                chiusura = ric + timedelta(days=int(durata))
                if chiusura > date(2026, 9, 30) or rng.random() < .04: chiusura = None   # ancora aperti
                if rng.random() < .05: consegna = None
                if rng.random() < .01: consegna = ric - timedelta(days=int(rng.integers(30, 400)))  # data sbagliata
                if op in refusi and rng.random() < .02: op = str(rng.choice(refusi[op]))
                qta = 1 if rng.random() < .9 else int(rng.choice([0, 2, 3, 4, 5, 10, 20, 50]))
                garanzia = int(eta <= 2 and rng.random() < .8)
                nota = None if rng.random() < .7 else str(rng.choice(NOTE_DIAGNOSI)).replace("{d}", "COMPONENTE")
                rientri.append((rid, num, anno, scheda, cli, art_id, qta, ddt, ddt_data, ric, consegna, chiusura, op, garanzia, nota))
                if rng.random() < .015:   # duplicato da copia-incolla, come negli archivi veri
                    rid += 1; rientri.append((rid, *rientri[-1][1:]))
                # pezzi sostituiti/riparati
                if op in ("spedito", "mpf") and rng.random() < .55:
                    comp = [c for c in COMPONENTI if c[2] == "all" or fam in c[2]]
                    for k in rng.choice(len(comp), size=int(rng.integers(1, 4)), replace=False):
                        pid += 1
                        c = comp[k]
                        pezzi.append((pid, rid, c[0], c[1], str(rng.choice(list("SSSSARO"))), 1))
    db.executemany("INSERT INTO rientri VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rientri)
    db.executemany("INSERT INTO pezzi_intervento VALUES (?,?,?,?,?,?)", pezzi)
    db.commit()
    print(f"{OUT}: {len(rientri)} rientri, {len(pezzi)} pezzi")


if __name__ == "__main__":
    main()
