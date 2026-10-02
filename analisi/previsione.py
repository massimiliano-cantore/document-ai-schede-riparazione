"""Tappa 3 - previsione dei rientri mensili.
Confronta 3 modelli su un test onesto (ultimi 12 mesi mai visti) e usa il migliore per i prossimi 6 mesi.
Uso: python analisi/previsione.py
"""
import warnings
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from analisi import carica, pulisci, OUT, plt, grafico

warnings.filterwarnings("ignore")
ORIZZONTE, TEST = 6, 12


def serie_mensile(d):
    s = d.groupby(d.ricevuto_il.dt.to_period("M")).size()
    s.index = s.index.to_timestamp()
    s = s.asfreq("MS", fill_value=0)
    # mesi finali con pochissimi dati = archivio non ancora aggiornato, non un vero calo: si escludono
    soglia = .4 * s.median()
    ok = (s.to_numpy() >= soglia) & (s.index.month.to_numpy() != 8)   # agosto e' basso per ferie, non conta
    if not ok.any():
        return s
    ultimo = ok.nonzero()[0][-1]
    return s.iloc[:ultimo + 1]


def modelli():
    """Ogni modello: storico -> previsione di h mesi."""
    def ingenuo_stagionale(s, h):          # "come lo stesso mese dell'anno scorso"
        return np.array([s.iloc[-12 + (i % 12)] for i in range(h)], float)

    def media_stagionale(s, h):            # livello degli ultimi 12 mesi x profilo medio del mese
        prof = s.groupby(s.index.month).mean() / s.mean()
        livello = s.iloc[-12:].mean()
        mesi = pd.date_range(s.index[-1] + pd.offsets.MonthBegin(), periods=h, freq="MS").month
        return livello * prof.loc[mesi].to_numpy()

    def holt_winters(s, h):                # livello + stagionalita' moltiplicativa (smorzata)
        m = ExponentialSmoothing(s.clip(lower=1), seasonal="mul", seasonal_periods=12, trend="add",
                                 damped_trend=True).fit()
        return m.forecast(h).to_numpy()

    return {"ingenuo stagionale": ingenuo_stagionale, "media stagionale": media_stagionale,
            "Holt-Winters": holt_winters}


def valuta(s):
    """Backtest a finestra mobile: ogni mese degli ultimi 12 previsto con i soli dati precedenti."""
    err = {}
    for nome, f in modelli().items():
        e = [abs(f(s.iloc[:len(s) - TEST + i], 1)[0] - s.iloc[len(s) - TEST + i]) for i in range(TEST)]
        err[nome] = np.mean(e)
    return pd.Series(err).sort_values()


def prevedi(d):
    s = serie_mensile(d)
    if len(s) < 24 + TEST:
        raise ValueError("servono almeno 3 anni di storico")
    err = valuta(s)
    migliore = err.index[0]
    futuro = pd.date_range(s.index[-1] + pd.offsets.MonthBegin(), periods=ORIZZONTE, freq="MS")
    prev = pd.Series(modelli()[migliore](s, ORIZZONTE), index=futuro).clip(lower=0).round()
    banda = err.iloc[0] * 1.5                # banda indicativa ~ errore medio del test
    return s, prev, banda, err


def main():
    d, _ = carica()
    d, _ = pulisci(d)
    s, prev, banda, err = prevedi(d)
    plt.figure(figsize=(11, 4.5))
    s.iloc[-36:].plot(label="storico")
    prev.plot(label="previsione", ls="--", marker="o")
    plt.fill_between(prev.index, prev - banda, prev + banda, alpha=.2)
    plt.legend(); plt.ylabel("rientri")
    grafico("07_previsione.png", f"Previsione rientri - {err.index[0]}")
    righe = ["\n## Previsione rientri (prossimi 6 mesi)",
             "Errore medio assoluto sugli ultimi 12 mesi (rientri/mese):"]
    righe += [f"- {k}: **{v:.1f}**" for k, v in err.items()]
    righe += ["", prev.rename("rientri previsti").to_frame().set_axis(prev.index.strftime("%m/%Y")).to_markdown(),
              "", "![previsione](07_previsione.png)"]
    rep = OUT / "report.md"
    testo = rep.read_text(encoding="utf-8").split("\n## Previsione")[0]
    rep.write_text(testo + "\n".join(righe), encoding="utf-8")
    print("\n".join(righe))


if __name__ == "__main__":
    main()
