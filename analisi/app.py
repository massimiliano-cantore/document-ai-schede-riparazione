"""Dashboard resi KYROS ACCESS (dati sintetici). Avvio: streamlit run analisi/app.py"""
import streamlit as st
from analisi import carica, pulisci, DB
import pandas as pd
from previsione import prevedi

st.set_page_config("Resi KYROS ACCESS", layout="wide")
if not DB.exists():
    import genera_db   # serve il generatore della tappa 2
    genera_db.main()


@st.cache_data
def dati():
    d, p = carica()
    d, log = pulisci(d)
    return d, p, log


d, p, log = dati()
st.title("Analisi resi e riparazioni - KYROS ACCESS")
st.caption("Azienda e dati interamente sintetici, generati per il portfolio.")

with st.sidebar:
    anni = st.multiselect("Anno", sorted(d.anno.unique()), default=sorted(d.anno.unique()))
    fam = st.multiselect("Famiglia", sorted(d.famiglia.unique()), default=sorted(d.famiglia.unique()))
f = d[d.anno.isin(anni) & d.famiglia.isin(fam)]

c = st.columns(4)
c[0].metric("Rientri", f"{len(f):,}".replace(",", "."))
c[1].metric("Clienti", f.cliente.nunique())
c[2].metric("Giorni mediani di lavorazione", f"{f.giorni_lavorazione.median():.0f}")
c[3].metric("Rottamati", f"{(f.operazione == 'rottamato').mean():.1%}")

m = f.groupby(f.ricevuto_il.dt.to_period("M")).size(); m.index = m.index.to_timestamp()
st.subheader("Rientri al mese"); st.line_chart(m)

st.subheader("Previsione prossimi 6 mesi")
s, prev, banda, err = prevedi(f)
tab = pd.DataFrame({"storico": s.iloc[-24:], "previsione": pd.concat([s.iloc[-1:], prev])})  # unisce le due linee
st.line_chart(tab, color=["#e8702a", "#1f5fbf"])
st.caption(f"Modello scelto: {err.index[0]} (errore medio {err.iloc[0]:.0f} rientri/mese sugli ultimi 12 mesi, "
           f"confrontato con: " + ", ".join(f"{k} {v:.0f}" for k, v in err.iloc[1:].items()) + ")")

a, b = st.columns(2)
a.subheader("Top 10 clienti"); a.bar_chart(f.cliente.value_counts().head(10).rename("count"), horizontal=True, sort="-count")
b.subheader("Top 10 articoli"); b.bar_chart(f.articolo.value_counts().head(10).rename("count"), horizontal=True, sort="-count")

a, b = st.columns(2)
pp = p[p.rientro_id.isin(f.id)]
pz = (pp.codice + " - " + pp.descrizione).value_counts().head(10)
a.subheader("Componenti più sostituiti"); a.bar_chart(pz.rename("count"), horizontal=True, sort="-count")
b.subheader("Esiti"); b.bar_chart(f.operazione.value_counts())

with st.expander("Qualità dei dati: cosa è stato corretto"):
    for k, v in log.items():
        st.write(f"- {k}: **{v}**")
