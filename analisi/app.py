"""Punto di ingresso della demo: dashboard sempre visibile, assistente solo quando abilitato.

L'assistente compare nel menu se nei Secrets di Streamlit c'e' MOSTRA_ASSISTENTE = true,
oppure (anteprima privata) aprendo l'app con ?anteprima=<ANTEPRIMA_CODICE>.
"""
import streamlit as st

st.set_page_config("Resi KYROS ACCESS", layout="wide")


def segreto(nome, default=""):
    try:
        return str(st.secrets.get(nome, default))
    except Exception:
        return default


codice = segreto("ANTEPRIMA_CODICE")
if codice and st.query_params.get("anteprima") == codice:
    st.session_state.anteprima = True
visibile = segreto("MOSTRA_ASSISTENTE").lower() == "true" or st.session_state.get("anteprima", False)

pagine = [st.Page("dashboard.py", title="Dashboard", icon="📊", default=True)]
if visibile:
    pagine.append(st.Page("assistente.py", title="Assistente", icon="💬"))
st.navigation(pagine).run()
