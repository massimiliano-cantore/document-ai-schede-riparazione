"""Tappa 4 - valutazione dell'agente: domande con risposta nota (calcolata con SQL scritto a mano).
Una risposta e' giusta se contiene tutti i valori attesi. Uso: GROQ_API_KEY=... python analisi/valuta_agente.py
"""
import json, re, time
from pathlib import Path
from agente import Database, chiedi, client

DOMANDE = [  # (domanda, SQL di riferimento: i valori della prima riga/colonne attese devono comparire nella risposta)
    ("Quanti rientri ci sono stati nel 2024?", "SELECT COUNT(*) FROM rientri WHERE anno=2024"),
    ("Quanti rientri sono ancora aperti?", "SELECT COUNT(*) FROM rientri WHERE data_chiusura IS NULL"),
    ("Qual è l'articolo con più rientri in assoluto?", "SELECT articolo FROM rientri GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("Quale cliente ha mandato più resi nel 2025?", "SELECT cliente FROM rientri WHERE anno=2025 GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("Quanti rientri sono stati rottamati in totale?", "SELECT COUNT(*) FROM rientri WHERE operazione='rottamato'"),
    ("Quale famiglia di prodotto ha più rientri?", "SELECT famiglia FROM rientri GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("In quale mese del 2023 sono arrivati più rientri? Dimmi il mese in formato AAAA-MM.",
     "SELECT strftime('%Y-%m', ricevuto_il) FROM rientri WHERE anno=2023 GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("Qual è il componente sostituito più spesso? Dammi il codice.",
     "SELECT codice FROM pezzi GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("Quanti clienti diversi hanno mandato almeno un reso nel 2022?", "SELECT COUNT(DISTINCT cliente) FROM rientri WHERE anno=2022"),
    ("Quanti rientri delle centraline erano in garanzia?", "SELECT COUNT(*) FROM rientri WHERE famiglia='centralina' AND in_garanzia=1"),
    ("Da quale provincia arrivano più resi?", "SELECT provincia FROM rientri GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("Quanti rientri ha mandato il cliente con più resi in assoluto?",
     "SELECT COUNT(*) FROM rientri GROUP BY cliente ORDER BY 1 DESC LIMIT 1"),
    ("Quanti rientri di serrature ci sono stati nel 2025?", "SELECT COUNT(*) FROM rientri WHERE famiglia='serratura' AND anno=2025"),
    ("Qual è il tempo mediano di lavorazione in giorni dei lettori? Arrotonda all'intero.",
     "SELECT CAST(ROUND(AVG(g)) AS INT) FROM (SELECT giorni_lavorazione g FROM rientri WHERE famiglia='lettore' "
     "AND g IS NOT NULL ORDER BY g LIMIT 2 - (SELECT COUNT(*) FROM rientri WHERE famiglia='lettore' AND giorni_lavorazione "
     "IS NOT NULL) % 2 OFFSET (SELECT (COUNT(*) - 1) / 2 FROM rientri WHERE famiglia='lettore' AND giorni_lavorazione IS NOT NULL))"),
    ("Quanti rientri di tipo 'mpf' ci sono stati nel 2024?", "SELECT COUNT(*) FROM rientri WHERE operazione='mpf' AND anno=2024"),
]


def norm(x):
    s = re.sub(r"(?<=\d)[.\s](?=\d{3}\b)", "", str(x))   # 1.651 / 1 651 -> 1651
    s = s.lower().replace("*", "").replace("`", "").replace("\u2011", "-").replace("\u2013", "-")
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
            "ottobre", "novembre", "dicembre"]
    for i, m in enumerate(mesi, 1):   # "gennaio 2023" -> "2023-01"
        s = re.sub(rf"{m}\s+(\d{{4}})", rf"\1-{i:02d}", s)
    return s


def main():
    db = Database()
    llm, modello = client()
    giuste, log = 0, []
    for domanda, sql in DOMANDE:
        atteso = [v for v in db.con.execute(sql).fetchone()]
        try:
            risposta, passi = chiedi(domanda, db, llm, modello)
        except Exception as e:
            risposta, passi = f"ERRORE {e}", []
        ok = all(re.search(rf"(?<![\w]){re.escape(norm(a))}(?![\w])", norm(risposta)) for a in atteso)
        giuste += ok
        log.append({"domanda": domanda, "atteso": atteso, "ok": ok, "risposta": risposta,
                    "query": [p["argomenti"] for p in passi]})
        print(("OK " if ok else "NO ") + domanda, "| atteso:", atteso)
        time.sleep(2)   # quota gratuita: poche richieste al minuto
    print(f"\nRisposte corrette: {giuste}/{len(DOMANDE)}")
    Path("valutazione_agente.json").write_text(json.dumps({"modello": modello, "corrette": giuste, "totale": len(DOMANDE),
                                                            "dettaglio": log}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
