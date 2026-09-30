# Document AI — schede di riparazione compilate a mano

Estrazione automatica dei dati da schede di riparazione **scansionate e compilate a mano** (fronte e retro),
con un modello vision-language **gratuito e locale** (Qwen2.5-VL-7B su GPU Kaggle T4) e un'accuratezza
**misurata campo per campo**.

Il progetto nasce da un caso reale (gestione resi e riparazioni di un produttore di sistemi di accesso).
Per pubblicarlo senza esporre documenti, clienti o codici reali, tutto quello che è nel repository è **sintetico**:
l'azienda *KYROS ACCESS* è fittizia e le schede sono generate. I documenti reali sono usati solo in privato.

## Il problema
Ogni scheda ha una parte stampata (numero riparazione, cliente, articolo, date) e una parte scritta a mano da tecnici diversi:
seriale, tempo di riparazione, firmware, una tabella di componenti sostituiti (codice, descrizione, intervento, causa, pezzi)
con "idem" scritti come `n` o virgolette, e note libere sul retro. Grafie diverse, stampatello irregolare, 4 "aperti", 7 con la stanghetta.

## 1. Generatore di schede sintetiche realistiche
`generator/genera_schede.py` produce PDF di 2 pagine + la **verità** in JSON.
La scrittura a mano non usa font: è composta con **inchiostro vero**, parole e caratteri ritagliati da ~260 schede reali
(1.530 ritagli trascritti, 482 parole, glifi per quasi tutto l'alfabeto e le cifre), con effetto scansione (rotazione, rumore, JPEG).
La raccolta dei ritagli resta privata e non è nel repository.

## 2. Pipeline di estrazione
1. **Lettura della pagina intera** (`esegui_qwen.py`): Qwen2.5-VL-7B legge fronte e retro e restituisce un JSON con schema fisso (`prompt.py`).
2. **Riparazione del JSON** (`ripara_json.py`) quando il modello sbaglia la sintassi.
3. **Correzione con il catalogo** (`correggi.py`): separa causa e intervento, risolve gli idem e aggancia codice + descrizione
   alla voce di catalogo più vicina a entrambe le letture (nel mondo reale il catalogo ricambi è nel gestionale).
4. **Seconda lettura mirata** (`esegui_campi.py` + `unisci_campi.py`): i campi liberi (seriale, date, tempo, firmware) vengono ritagliati,
   ingranditi e riletti due volte; si vota fra le tre letture scartando quelle che violano il formato.
   **Se le letture non coincidono il campo viene segnalato come incerto** e va a revisione umana.
5. **Valutazione** (`valuta.py`): accuratezza per campo, schede perfette, errori intercettati dalla segnalazione.

## Risultati (100 schede sintetiche di test, Qwen2.5-VL-7B, ~65 s/scheda su Kaggle T4, costo 0)

| | Solo modello | + catalogo | + seconda lettura |
|---|---|---|---|
| Campi stampati | 100% | 100% | 100% |
| Campi scritti a mano | 56% | 84% | **85%** |
| Codice componente | 23% | 95% | **95%** |
| Intervento / causa | 14% / 41% | 89% / 74% | **89% / 74%** |
| Data produzione / eseguito il | 61% / 81% | = | **73% / 85%** |
| Firmware | 82% | = | **87%** |
| Seriale | 28% | = | **32%** |
| Parole delle note ritrovate | 72% | = | **72%** |
| **Errori segnalati come incerti** | 8% | 29% | **70%** |

**Lettura dei risultati.** Lo stampato è risolto. Dove esiste un vocabolario chiuso (catalogo) l'errore di lettura si recupera quasi tutto.
I campi numerici liberi scritti a mano (il seriale soprattutto) restano il limite di un modello 7B: la risposta del sistema è
**sapere quando non sa**. Con la segnalazione, 7 errori su 10 vengono indirizzati a un controllo umano, invece di finire nel database.

## Limiti e prossimi passi
- Numeri misurati su schede sintetiche; la validazione su schede reali avviene in privato.
- Seriale: provare un modello più grande o un OCR di sole cifre sul ritaglio.
- La segnalazione è ancora prudente (molti campi corretti segnalati): da calibrare.

## Struttura
```
generator/    genera_schede.py, inchiostro_reale.py, mano_tratti.py
estrazione/   prompt.py, schema.py, esegui_qwen.py, esegui_campi.py, ripara_json.py, correggi.py, unisci_campi.py, valuta.py, catalogo.json
risultati/    report JSON delle tre fasi
```
