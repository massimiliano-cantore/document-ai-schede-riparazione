"""Tappa 4 - agente che risponde in italiano a domande sui resi, interrogando il database.

L'LLM non vede i dati: vede lo schema e due strumenti (SQL in sola lettura, previsione).
Funziona con qualsiasi API compatibile OpenAI; di default Groq (gratuito):
    export GROQ_API_KEY=...   ->   python analisi/agente.py "quali articoli tornano di piu' nel 2025?"
"""
import json
import os
import re
import sqlite3
import sys

import pandas as pd

from analisi import carica, pulisci
from previsione import prevedi

PROVIDER = {  # nome -> (base_url, modello di default)
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
}
MAX_RIGHE, MAX_PASSI = 50, 8

SCHEMA = """Tabelle (SQLite) dei resi di KYROS ACCESS, azienda fittizia che ripara serrature, cilindri, centraline,
lettori e tastiere. I dati sono gia' puliti (duplicati tolti, esiti normalizzati, date impossibili rimosse).

rientri(id, riparazione_numero TEXT es '16/10', anno INT, scheda_progressiva INT, cliente TEXT, provincia TEXT,
        tipo_cliente TEXT, articolo TEXT, famiglia TEXT, quantita INT, ddt_numero TEXT, ddt_data DATE,
        ricevuto_il DATE, scheda_consegnata DATE, data_chiusura DATE, giorni_lavorazione REAL,
        operazione TEXT, in_garanzia INT 0/1, note TEXT)
  - una riga = un pezzo rientrato (pezzi uguali dello stesso reso hanno scheda_progressiva diversa)
  - famiglia in ('serratura','cilindro','centralina','lettore','tastiera')
  - operazione = esito: 'spedito' (riparato e rispedito), 'mpf' (in attesa/messo fuori produzione), 'rottamato',
    'sostituito', 'reso a cliente'; NULL = ancora aperto (anche data_chiusura NULL)
  - date in formato 'YYYY-MM-DD'; usa strftime('%Y-%m', ricevuto_il) per i mesi
pezzi(rientro_id -> rientri.id, codice TEXT es 'SCB1180', descrizione TEXT es 'CIRCUITO',
      intervento TEXT 'S'=sostituito 'A'=aggiornato 'R'=riparato 'O'=altro, quantita INT)
Dati disponibili da gennaio 2022 a settembre 2026."""

ISTRUZIONI = f"""Sei l'assistente dell'ufficio riparazioni di KYROS ACCESS. Rispondi in italiano, in modo breve e preciso.
Per ogni numero usa gli strumenti: non inventare mai dati. Se una domanda e' ambigua, scegli l'interpretazione
piu' ragionevole e dichiarala in una frase. Se i dati non bastano a rispondere, dillo.
Nelle risposte con piu' valori usa un elenco o una piccola tabella markdown.

{SCHEMA}"""

STRUMENTI = [
    {"type": "function", "function": {
        "name": "esegui_sql",
        "description": "Esegue UNA query SQLite di sola lettura (SELECT o WITH) sul database dei resi e restituisce "
                       f"al massimo {MAX_RIGHE} righe. Usa GROUP BY, COUNT, AVG, ORDER BY, LIMIT per riassumere.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "previsione_rientri",
        "description": "Prevede i rientri dei prossimi 6 mesi (totale o per una famiglia di prodotto), "
                       "con il modello migliore su backtest e il suo errore medio.",
        "parameters": {"type": "object", "properties": {
            "famiglia": {"type": "string", "description": "facoltativa: serratura, cilindro, centralina, lettore, tastiera"}}}}},
]


class Database:
    """Copia in memoria dei dati puliti, aperta in sola lettura per l'agente."""

    def __init__(self):
        d, p = carica()
        d, _ = pulisci(d)
        self.df = d
        d = d.drop(columns=["mese", "cliente_id", "articolo_id"]).copy()
        for c in ["ddt_data", "ricevuto_il", "scheda_consegnata", "data_chiusura"]:
            d[c] = d[c].dt.strftime("%Y-%m-%d")
        p = p[p.rientro_id.isin(d.id)].drop(columns=["id"])
        uri = "file:resi_agente?mode=memory&cache=shared"
        self._scrittura = sqlite3.connect(uri, uri=True, check_same_thread=False)   # tiene viva la memoria
        d.to_sql("rientri", self._scrittura, index=False, if_exists="replace")
        p.to_sql("pezzi", self._scrittura, index=False, if_exists="replace")
        self.con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.con.execute("PRAGMA query_only = ON")

    def sql(self, query):
        q = query.strip().rstrip(";")
        if not re.match(r"(?is)^\s*(select|with)\b", q) or ";" in q:
            return {"errore": "ammessa solo una singola query SELECT/WITH"}
        try:
            r = pd.read_sql(q, self.con)
        except Exception as e:  # l'errore torna al modello, che puo' correggere la query
            return {"errore": str(e)[:300]}
        return {"righe_totali": len(r), "righe": json.loads(r.head(MAX_RIGHE).to_json(orient="records", force_ascii=False))}

    def previsione(self, famiglia=None):
        d = self.df if not famiglia else self.df[self.df.famiglia == famiglia.lower().strip()]
        if d.empty:
            return {"errore": f"famiglia sconosciuta: {famiglia}"}
        s, prev, _, err = prevedi(d)
        return {"modello": err.index[0], "errore_medio_mensile": round(float(err.iloc[0]), 1),
                "ultimo_mese_dati": s.index[-1].strftime("%Y-%m"),
                "previsione": {k.strftime("%Y-%m"): int(v) for k, v in prev.items()}}


def client(provider=None, api_key=None, modello=None):
    from openai import OpenAI
    provider = provider or os.getenv("LLM_PROVIDER", "groq")
    url, mod = PROVIDER[provider]
    key = api_key or os.getenv(f"{provider.upper()}_API_KEY")
    if not key:
        raise RuntimeError(f"manca la chiave {provider.upper()}_API_KEY")
    llm = OpenAI(base_url=url, api_key=key)
    scelto = modello or os.getenv("LLM_MODEL")
    if not scelto:
        scelto = scegli_modello(llm, mod)
    return llm, scelto


PREFERITI = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct",
             "qwen/qwen3-32b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]


def scegli_modello(llm, default):
    """I modelli gratuiti cambiano spesso: si sceglie il primo dei preferiti ancora disponibile."""
    try:
        disponibili = {m.id for m in llm.models.list().data}
    except Exception:
        return default
    for m in [default] + PREFERITI:
        if m in disponibili:
            return m
    return sorted(disponibili)[0] if disponibili else default


def chiedi(domanda, db, llm, modello, storia=None):
    """Ciclo agente: il modello chiama strumenti finche' non ha la risposta.
    Restituisce (risposta, passi) dove passi elenca le chiamate fatte, per trasparenza."""
    messaggi = [{"role": "system", "content": ISTRUZIONI}] + (storia or []) + [{"role": "user", "content": domanda}]
    passi = []
    for _ in range(MAX_PASSI):
        r = llm.chat.completions.create(model=modello, messages=messaggi, tools=STRUMENTI, temperature=0)
        m = r.choices[0].message
        if not m.tool_calls:
            return m.content or "", passi
        messaggi.append({"role": "assistant", "content": m.content or "",
                         "tool_calls": [{"id": t.id, "type": "function",
                                         "function": {"name": t.function.name, "arguments": t.function.arguments}}
                                        for t in m.tool_calls]})
        for t in m.tool_calls:
            try:
                arg = json.loads(t.function.arguments or "{}")
            except json.JSONDecodeError:
                arg = {}
            if t.function.name == "esegui_sql":
                out = db.sql(arg.get("query", ""))
            elif t.function.name == "previsione_rientri":
                out = db.previsione(arg.get("famiglia"))
            else:
                out = {"errore": "strumento sconosciuto"}
            passi.append({"strumento": t.function.name, "argomenti": arg, "esito": out})
            messaggi.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(out, ensure_ascii=False)[:6000]})
    return "Non sono riuscito a completare la risposta entro il numero massimo di passi.", passi


if __name__ == "__main__":
    llm, mod = client()
    risposta, passi = chiedi(" ".join(sys.argv[1:]) or "Quanti rientri ci sono stati nel 2025?", Database(), llm, mod)
    for p in passi:
        print(">>", p["strumento"], p["argomenti"])
    print(risposta)
