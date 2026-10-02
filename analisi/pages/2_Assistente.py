"""Chat con l'agente che interroga il database dei resi (dati sintetici KYROS ACCESS)."""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agente import Database, chiedi, client

st.set_page_config("Assistente resi", layout="wide")
st.title("Assistente resi - KYROS ACCESS")
st.caption("Fai una domanda in italiano: l'agente scrive le query SQL sul database (sintetico) e risponde. "
           "Sotto ogni risposta puoi vedere le query usate.")
LIMITE = 15  # domande per sessione, per non esaurire la quota gratuita della demo
ESEMPI = ["Quali sono i 5 articoli che tornano di più nel 2025?",
          "Quanti rientri sono ancora aperti, divisi per famiglia?",
          "Qual è il tempo medio di lavorazione delle centraline anno per anno?",
          "Quali componenti si sostituiscono più spesso sulle serrature?",
          "Quanti rientri prevedi per le serrature nei prossimi mesi?"]


@st.cache_resource
def database():
    return Database()


def chiave():
    try:
        if "LLM_MODEL" in st.secrets:
            os.environ["LLM_MODEL"] = st.secrets["LLM_MODEL"]
    except Exception:
        pass
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        try:
            if k in st.secrets:
                os.environ[k] = st.secrets[k]
                os.environ["LLM_PROVIDER"] = k.split("_")[0].lower()
                return True
        except Exception:
            pass
        if os.getenv(k):
            return True
    return False


if not chiave():
    st.warning("Chiave API non configurata (GROQ_API_KEY nei Secrets di Streamlit).")
    st.stop()

db = database()
llm, modello = client()
st.session_state.setdefault("chat", [])

with st.sidebar:
    st.subheader("Prova con:")
    for e in ESEMPI:
        if st.button(e, use_container_width=True):
            st.session_state.domanda = e
    if st.button("Nuova conversazione"):
        st.session_state.chat = []


def mostra_passi(passi):
    if not passi:
        return
    with st.expander(f"Come ho trovato la risposta ({len(passi)} passi)"):
        for p in passi:
            if p["strumento"] == "esegui_sql":
                st.code(p["argomenti"].get("query", ""), language="sql")
                e = p["esito"]
                if "righe" in e and e["righe"]:
                    st.dataframe(pd.DataFrame(e["righe"]).head(10), hide_index=True)
                elif "errore" in e:
                    st.caption(f"errore, query corretta al passo successivo: {e['errore']}")
            else:
                st.write(f"Previsione {p['argomenti'] or '(totale)'}: modello {p['esito'].get('modello', '')}")


for m in st.session_state.chat:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        mostra_passi(m.get("passi"))

domanda = st.chat_input("Scrivi una domanda sui resi...") or st.session_state.pop("domanda", None)
if domanda:
    n = sum(m["role"] == "user" for m in st.session_state.chat)
    with st.chat_message("user"):
        st.markdown(domanda)
    with st.chat_message("assistant"):
        if n >= LIMITE:
            st.info("Limite di domande della demo raggiunto: apri una nuova conversazione.")
            st.stop()
        with st.spinner("Interrogo il database..."):
            storia = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat[-6:]]
            try:
                risposta, passi = chiedi(domanda, db, llm, modello, storia)
            except Exception as e:
                risposta, passi = f"Il servizio del modello non risponde ora ({type(e).__name__}). Riprova tra poco.", []
        st.markdown(risposta)
        mostra_passi(passi)
    st.session_state.chat += [{"role": "user", "content": domanda},
                              {"role": "assistant", "content": risposta, "passi": passi}]
