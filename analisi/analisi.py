"""Tappa 3 - pulizia e analisi dei resi (database sintetico KYROS ACCESS).
Uso: python analisi/analisi.py -> analisi/report/ (grafici PNG + report.md)
"""
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.size": 14, "axes.titlesize": 17, "axes.titleweight": "bold", "axes.labelsize": 14,
                     "xtick.labelsize": 13, "ytick.labelsize": 13, "axes.spines.top": False, "axes.spines.right": False})

QUI = Path(__file__).parent
DB, OUT = QUI / "dati" / "resi_kyros.db", QUI / "report"
NORMA_OP = {"speditp": "spedito", "spedita": "spedito", "rottamata": "rottamato", "rottamare": "rottamato"}


def carica(db=DB):
    c = sqlite3.connect(db)
    d = pd.read_sql("""SELECT r.*, c.nome cliente, c.provincia, c.tipo tipo_cliente, a.codice articolo, a.famiglia
                       FROM rientri r JOIN clienti c ON c.id=r.cliente_id JOIN articoli a ON a.id=r.articolo_id""", c)
    p = pd.read_sql("SELECT * FROM pezzi_intervento", c)
    return d, p


def pulisci(d, oggi="2026-09-30", togli_duplicati=True):
    """Restituisce (dati puliti, registro dei problemi trovati)."""
    log = {}
    for col in ["ddt_data", "ricevuto_il", "scheda_consegnata", "data_chiusura"]:
        d[col] = pd.to_datetime(d[col])
    # duplicato = riga identica in tutto, numero di scheda compreso. Pezzi uguali dello stesso reso
    # hanno ciascuno la propria scheda (1, 2, 3...) e sono rientri distinti, non doppioni.
    chiave = [c for c in d.columns if c != "id"]
    log["righe copiate due volte (stessa scheda)"] = int(d.duplicated(chiave).sum())
    if togli_duplicati:
        d = d.drop_duplicates(chiave)
    futuro = d.ricevuto_il > pd.Timestamp(oggi)
    log["date di arrivo nel futuro (scartate)"] = int(futuro.sum())
    d = d[~futuro & d.ricevuto_il.notna()].copy()
    op = d.operazione.str.lower().str.strip()
    log["esiti scritti male"] = int(op.isin(list(NORMA_OP)).sum())
    d["operazione"] = op.replace(NORMA_OP)
    sbagliate = d.scheda_consegnata < d.ricevuto_il
    log["date di consegna precedenti all'arrivo"] = int(sbagliate.sum())
    d.loc[sbagliate, "scheda_consegnata"] = pd.NaT
    log["quantita' zero"] = int((d.quantita == 0).sum())
    d["giorni_lavorazione"] = (d.data_chiusura - d.ricevuto_il).dt.days
    neg = d.giorni_lavorazione < 0
    log["chiusure precedenti all'arrivo"] = int(neg.sum())
    d.loc[neg, ["data_chiusura", "giorni_lavorazione"]] = [pd.NaT, None]
    d["mese"] = d.ricevuto_il.dt.to_period("M")
    return d, log


def grafico(nome, titolo):
    plt.title(titolo); plt.tight_layout(); plt.savefig(OUT / nome, dpi=150); plt.close()


def main():
    OUT.mkdir(exist_ok=True)
    d, p = carica()
    d, log = pulisci(d)
    righe = ["# Analisi resi - KYROS ACCESS (dati sintetici)\n", "## Qualità dei dati"]
    righe += [f"- {k}: **{v}**" for k, v in log.items()]

    # volumi mensili
    m = d.groupby("mese").size(); m.index = m.index.to_timestamp()
    x = np.arange(len(m)); pend, quota = np.polyfit(x, m.to_numpy(), 1)
    plt.figure(figsize=(11, 4.5))
    plt.plot(m.index, m, color="#9bb7e0", label="rientri")
    plt.plot(m.index, m.rolling(6).mean(), color="#e8702a", lw=2.5, label="media mobile 6 mesi")
    plt.plot(m.index, pend * x + quota, "k--", lw=1.5, label=f"tendenza ({pend * 12:+.0f}/mese all'anno)")
    plt.legend(loc="lower left", fontsize=12); plt.ylabel("rientri"); grafico("01_volumi_mensili.png", "Rientri al mese")
    stag = d.groupby(d.ricevuto_il.dt.month).size() / d.anno.nunique()
    plt.figure(figsize=(9, 5)); stag.plot.bar(); plt.xlabel("mese"); grafico("02_stagionalita.png", "Media rientri per mese dell'anno")

    # pareto clienti / articoli
    cl = d.cliente.value_counts()
    quota10 = cl.head(10).sum() / len(d)
    plt.figure(figsize=(9, 5)); (cl.cumsum() / len(d)).reset_index(drop=True).plot(); plt.axhline(.8, ls=":")
    plt.xlabel("numero di clienti"); plt.ylabel("quota cumulata"); grafico("03_pareto_clienti.png", "Concentrazione dei resi per cliente")

    fam = d.groupby("famiglia").agg(rientri=("id", "size"), giorni_mediani=("giorni_lavorazione", "median"),
                                    rottamati=("operazione", lambda s: (s == "rottamato").mean() * 100)).round(1)
    plt.figure(figsize=(9, 5)); fam.rientri.sort_values().plot.barh(); grafico("04_famiglie.png", "Rientri per famiglia di prodotto")

    # tempi
    t = d.groupby(d.ricevuto_il.dt.to_period("Q")).giorni_lavorazione.median(); t.index = t.index.to_timestamp()
    plt.figure(figsize=(11, 4.5)); t.plot(marker="o"); plt.ylabel("giorni"); grafico("05_tempi.png", "Tempo mediano di lavorazione (trimestre)")

    # componenti più sostituiti
    pp = p[p.rientro_id.isin(d.id)]
    pz = pp.groupby(pp.codice + " - " + pp.descrizione).size().sort_values().tail(12)
    plt.figure(figsize=(9, 6)); pz.plot.barh(); grafico("06_componenti.png", "Componenti più sostituiti/riparati")

    aperti = d.data_chiusura.isna().sum()
    righe += ["\n## Numeri chiave",
              f"- rientri (dopo pulizia): **{len(d)}**, clienti: **{d.cliente.nunique()}**, articoli: **{d.articolo.nunique()}**",
              f"- i 10 clienti principali generano il **{quota10:.0%}** dei resi",
              f"- tempo mediano di lavorazione: **{d.giorni_lavorazione.median():.0f} giorni** (aperti: {aperti})",
              f"- esiti: " + ", ".join(f"{k} {v:.0%}" for k, v in d.operazione.value_counts(normalize=True).items()),
              "\n## Per famiglia\n", fam.to_markdown(),
              "\n## Grafici\n"] + [f"![{f.stem}]({f.name})" for f in sorted(OUT.glob("*.png"))]
    (OUT / "report.md").write_text("\n".join(righe), encoding="utf-8")
    print("\n".join(righe[:12]))


if __name__ == "__main__":
    main()
