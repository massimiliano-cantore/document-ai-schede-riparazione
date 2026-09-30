"""Generatore di schede di riparazione sintetiche con verità di riferimento.

Ogni scheda è un PDF di 2 pagine (A4, 150 dpi) con parti stampate e parti "scritte a mano",
degradato come una scansione reale, più un JSON con i valori corretti di ogni campo.
Azienda, clienti, articoli e codici sono inventati.

Uso:  python genera_schede.py --n 50 --out ../data/sintetici --seed 0
"""
import argparse
import io
import json
import math
import os
import random
import re
from inchiostro_reale import Inchiostro, disponibile as inchiostro_disponibile
from dataclasses import dataclass, asdict, field
from datetime import date, timedelta

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from mano_tratti import Scrittore

QUI = os.path.dirname(os.path.abspath(__file__))
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H = 1240, 1754                      # A4 a 150 dpi
AZIENDA = "KYROS ACCESS"               # azienda fittizia

# ---------------------------------------------------------------- dominio inventato
CLIENTI = ["EDILNOVA COSTRUZIONI", "SICURTECH IMPIANTI", "ALFA SERRAMENTI", "GRUPPO BORGHI SRL", "IMPIANTI ROSSETTI",
           "TECNOPORTE SNC", "CASA&CO SERVIZI", "ELETTRO VALLI", "DOMUS SYSTEM", "FERRAMENTA CENTRALE", "HOTEL AURORA",
           "RESIDENCE I PINI", "LOGISTICA PADANA", "STUDIO TECNICO MARTINI", "COOPERATIVA EDILE EST", "PORTE & FINESTRE SPA"]
ARTICOLI = {  # articolo -> famiglia
    "20410": "serratura", "20415": "serratura", "31220": "lettore", "31225": "lettore", "40801": "centralina",
    "40806": "centralina", "52100": "tastiera", "52130": "tastiera", "60050": "cilindro", "60075": "cilindro"}
COMPONENTI = [  # codice, descrizione, famiglie (lessico coperto dalla banca di inchiostro reale)
    ("SCA4471N", "SCATOLA NEUTRA", "centralina lettore"), ("CAV2210", "CAVO", "all"), ("SEN4420", "SENSORE MAGNETICO", "serratura centralina"),
    ("MOL2201", "MOLLA", "serratura cilindro"), ("LEV3301", "LEVA", "serratura"), ("CON1015", "CONNETTORE", "all"),
    ("SCB1180", "CIRCUITO", "all"), ("BOB5510", "BOBINA", "lettore"), ("MOT3302", "MOTORINO", "serratura cilindro"),
    ("PIG1120", "PIGNONE", "serratura cilindro"), ("PER0907", "PERNO", "serratura cilindro"), ("NOT2290", "NOTTOLINO", "cilindro"),
    ("GUI0815", "GUIDA", "serratura"), ("RUO7702", "RUOTA DENTATA", "serratura"), ("IMP5601", "IMPUGNATURA", "serratura"),
    ("CAT3310", "CATENACCIO", "serratura"), ("TIR0012", "TIRANTE", "serratura"), ("BOC0040", "BOCCOLA", "cilindro"),
    ("MIC1195", "MICRO", "centralina tastiera lettore"), ("GUA4420", "GUAINA ISOLANTE", "all"), ("SEN4425", "SENSORE REED", "centralina")]
INTERVENTI = ["SOSTITUZIONE", "SOSTITUZIONE", "SOSTITUZIONE", "PULIZIA", "MODIFICA"]
CAUSE = ["ROTTO", "MANCANTE", "BRUCIATO", "USURATO", "DEFORMATO", "OBSOLETO", "ROTTO", "MANCANTE", None]
NOTE_DIAGNOSI = [  # frasi sul modello delle note reali, con parole presenti nella banca di inchiostro
    "SERRATURA MOLTO VECCHIA CON CIRCUITO BRUCIATO, PER RIPARAZIONE BISOGNA AGGIORNARE PRATICAMENTE L'INTERA SERRATURA.",
    "NON RISCONTRATO DIFETTO LAMENTATO DAL CLIENTE.", "NESSUN PROBLEMA RISCONTRATO.", "NESSUNA ANOMALIA RISCONTRATA.",
    "MECCANICA PARZIALMENTE BLOCCATA. MOLLA NOTTOLINO ROTTA, DA SOSTITUIRE.", "INFILTRAZIONE ACQUA, CIRCUITO SPORCO.",
    "SERRATURA SPORCA DA PULIRE.", "GUIDA CATENACCIO AMMACCATA, DA SOSTITUIRE.", "SI SOSTITUISCE CIRCUITO CON NUOVO.",
    "PRESENTA PISTE INTERROTTE SUL CIRCUITO.", "BOBINA E NUCLEO BLOCCATO, SOSTITUIRE.", "LEVA CILINDRO DEFORMATA.",
    "{d} ROTTO, DA SOSTITUIRE.", "{d} MANCANTE.", "{d} SOSTITUITO CON NUOVO.", "RICHIESTA CLIENTE.",
    "CATENACCIO BLOCCATO, SOSTITUIRE GUIDA.", "TENSIONE COSTANTE, NON RISCONTRATO PROBLEMA."]
NOTE_ESITO = ["PULIZIA + COLLAUDO", "PULIZIA + COLLAUDO", "REVISIONE GENERALE", "AGGIORNARE V17", "COLLAUDO", None]
NOTE_ACCESSORI = ["SENZA SCATOLA, SENZA ACCESSORI", "PRIVO ACCESSORI", "COMPLETO DI ACCESSORI", "SENZA ACCESSORI", None, None]


def genera_note(rng, righe):
    """Le note sono sempre compilate: diagnosi (1-3 righe) + eventuale esito + accessori."""
    d = righe[0].descrizione if righe else "CIRCUITO"
    parti = [str(rng.choice(NOTE_DIAGNOSI)).format(d=d)]
    if rng.random() < .3:
        parti[0] += " " + str(rng.choice(NOTE_DIAGNOSI)).format(d=d)
    for lista in (NOTE_ESITO, NOTE_ACCESSORI):
        x = lista[int(rng.integers(len(lista)))]
        if x: parti.append(x)
    return "\n".join(parti)


@dataclass
class Riga:
    codice: str
    descrizione: str
    intervento: str
    causa: str | None
    pz: int
    intervento_idem: bool = False      # scritto come "n" (idem) sulla scheda
    causa_idem: bool = False


@dataclass
class Scheda:
    doc_id: str
    riparazione_n: str
    data: str
    cliente: str
    articolo: str
    pezzi: int
    ricevuto_il: str
    ddt_n: str | None
    ddt_del: str | None
    prodotto_il: str | None
    seriale: str
    aperta_manomessa: bool | None
    tempo_riparazione_min: int | None
    firmware: str | None
    righe: list = field(default_factory=list)
    note: str | None = None
    eseguito_il: str | None = None


def it(d):
    return d.strftime("%d/%m/%Y")


def campiona_scheda(rng, idx, giorno0=date(2023, 1, 9)):
    d = giorno0 + timedelta(days=int(rng.integers(0, 700)))
    art = str(rng.choice(list(ARTICOLI)))
    fam = ARTICOLI[art]
    comp = [c for c in COMPONENTI if c[2] == "all" or fam in c[2]]
    n_righe = int(rng.choice([0, 1, 1, 2, 2, 3, 3, 4, 5, 7, 13], p=[.04, .14, .14, .16, .16, .12, .1, .06, .04, .02, .02]))
    righe, prev = [], None
    for k in range(n_righe):
        cod, desc, _ = comp[int(rng.integers(len(comp)))]
        if prev is not None and rng.random() < 0.55:
            interv, idem = prev.intervento, True
        else:
            interv, idem = str(rng.choice(INTERVENTI)), False
        causa = CAUSE[int(rng.integers(len(CAUSE)))] if interv in ("SOSTITUZIONE", "MODIFICA") else None
        causa_idem = bool(prev is not None and idem and causa is not None and causa == prev.causa)
        if prev is not None and idem and prev.causa and rng.random() < 0.5:
            causa, causa_idem = prev.causa, True
        r = Riga(cod, desc, interv, causa, int(rng.choice([1, 1, 1, 1, 2, 3])), idem, causa_idem)
        righe.append(r); prev = r
    has_ddt = rng.random() < 0.35
    prod = d - timedelta(days=int(rng.integers(90, 2500)))
    fw = f"V{rng.integers(1, 25)}" + (f".{rng.integers(0, 10)}" if rng.random() < .25 else "")
    return Scheda(
        doc_id=f"SYN-{idx:05d}", riparazione_n=f"{int(rng.integers(1, 60)):02d}/{d.month:02d}", data=it(d),
        cliente=str(rng.choice(CLIENTI)), articolo=art, pezzi=1 if rng.random() < .85 else int(rng.integers(2, 5)),
        ricevuto_il=it(d - timedelta(days=int(rng.integers(0, 6)))),
        ddt_n=str(rng.integers(100, 2999)) if has_ddt else None, ddt_del=it(d - timedelta(days=int(rng.integers(1, 20)))) if has_ddt else None,
        prodotto_il=(prod.strftime("%m/%Y") if rng.random() < .5 else None),
        seriale=(f"{int(rng.integers(1000, 9999))}/{int(rng.integers(1000, 9999))}" if rng.random() < .5 else f"{int(rng.integers(0, 999999)):06d}"),
        aperta_manomessa=(None if rng.random() < .1 else bool(rng.random() < .15)),
        tempo_riparazione_min=(None if rng.random() < .1 else int(rng.choice([5, 10, 15, 20, 30, 45, 60, 90]))),
        firmware=(fw if fam in ("centralina", "tastiera", "lettore") and rng.random() < .7 else None),
        righe=righe, note=genera_note(rng, righe),
        eseguito_il=(it(d + timedelta(days=int(rng.integers(0, 10)))) if rng.random() < .4 else None))


# ---------------------------------------------------------------- scrittura "a mano"
class Mano:
    """Una persona che compila: stile costante nel documento (vedi mano_tratti.Scrittore)."""

    def __init__(self, rng):
        self.rng = rng
        self.s = Scrittore(rng)
        self.maiuscolo = self.s.maiuscolo
        self.color = tuple(int(c) for c in self.s.colore)
        self.ink = Inchiostro(rng, self.s.colore) if inchiostro_disponibile() else None
        if self.ink: self.maiuscolo = True          # nelle schede reali si scrive in stampatello

    def scrivi(self, img, xy, testo, max_w=None, idem=False, esatto=False):
        if not testo:
            return
        if not esatto:                              # codici, seriali e date restano come sono
            testo = testo.upper() if self.maiuscolo else testo.lower()
        if idem:                                    # la "n" di "idem" resta sempre minuscola
            testo = re.sub(r"\bN\b", "n", testo)
        if idem and self.ink and self.rng.random() < .4:
            testo = re.sub(r"\bn\b", '"', testo)    # idem anche come virgolette
        layer = (self.ink.rendi(testo, self.s.rendi) if self.ink else None) or self.s.rendi(testo)
        if max_w and layer.width > max_w:           # chi scrive stringe la grafia se lo spazio non basta
            r = max_w / layer.width
            layer = layer.resize((int(layer.width * r), max(1, int(layer.height * (0.5 + r / 2)))), Image.LANCZOS)
        img.paste(layer, (int(xy[0] + self.rng.normal(0, 3)), int(xy[1] - layer.height / 2 + self.rng.normal(0, 3))), layer)

    def barra(self, img, x, y, w):
        """Segno "/" o trattino per campo vuoto."""
        dr = ImageDraw.Draw(img)
        if self.rng.random() < .5:
            dr.line([(x, y + 12), (x + 30, y - 12)], fill=self.color, width=3)
        else:
            dr.line([(x, y + 4), (x + min(w, 90), y - 6)], fill=self.color, width=3)

    def croce(self, img, x, y):
        dr = ImageDraw.Draw(img)
        s = 12
        dr.line([(x - s, y - s), (x + s, y + s)], fill=self.color, width=3)
        dr.line([(x - s, y + s), (x + s, y - s)], fill=self.color, width=3)


# ---------------------------------------------------------------- impaginazione
def f(size, bold=False):
    return ImageFont.truetype(SANS_B if bold else SANS, size)


def box(dr, xy, w=2):
    dr.rectangle(xy, outline=(0, 0, 0), width=w)


def tratteggio(dr, y, x0=40, x1=W - 40):
    for x in range(x0, x1, 40):
        dr.line([(x, y), (x + 20, y)], fill=(90, 90, 90), width=2)


def dotted_h(dr, x0, x1, y):
    for x in range(x0, x1, 6):
        dr.point((x, y), fill=(0, 0, 0)); dr.point((x + 1, y), fill=(0, 0, 0))


def tabella(img, dr, mano, y0, righe, n_slot, idem_prob_scrittura=1.0):
    cols = [35, 305, 555, 1135, 1190]
    dr.rectangle([cols[0], y0, cols[-1], y0 + 45], outline=(0, 0, 0), width=2)
    for x, t in zip([cols[0], cols[1], cols[2], cols[3]], ["Codice o disegno", "Descrizione", "Intervento", "Pz."]):
        cx = (x + [cols[1], cols[2], cols[3], cols[4]][[cols[0], cols[1], cols[2], cols[3]].index(x)]) / 2
        dr.text((cx, y0 + 22), t, font=f(20, True), fill=(0, 0, 0), anchor="mm")
    y, hr = y0 + 45, 59
    for i in range(n_slot):
        for x in cols[1:-1]:
            for yy in range(y, y + hr, 6):
                dr.point((x, yy), fill=(0, 0, 0))
        dotted_h(dr, cols[0], cols[-1], y + hr)
        if i < len(righe):
            r = righe[i]; cy = y + hr / 2 + 4
            mano.scrivi(img, (cols[0] + 10, cy), r.codice, cols[1] - cols[0] - 20, esatto=True)
            mano.scrivi(img, (cols[1] + 10, cy), r.descrizione, cols[2] - cols[1] - 20)
            testo = "n" if r.intervento_idem else r.intervento
            if r.causa:
                testo += "   (" + ("n" if r.causa_idem else r.causa) + ")"
            mano.scrivi(img, (cols[2] + (120 if r.intervento_idem else 15), cy), testo, cols[3] - cols[2] - 30, idem=True)
            mano.scrivi(img, (cols[3] + 12, cy), str(r.pz), 40)
        y += hr
    dr.line([(cols[0], y0), (cols[0], y)], fill=(0, 0, 0), width=2)
    dr.line([(cols[-1], y0), (cols[-1], y)], fill=(0, 0, 0), width=2)
    return y


def pagina1(s, mano, rng):
    img = Image.new("RGB", (W, H), "white"); dr = ImageDraw.Draw(img)
    tratteggio(dr, 62)
    # logo fittizio
    dr.rectangle([45, 95, 95, 175], outline=(0, 0, 0), width=4); dr.line([(70, 95), (70, 175)], fill=(0, 0, 0), width=4)
    dr.text((110, 100), AZIENDA.split()[0], font=f(58, True), fill=(0, 0, 0))
    dr.text((112, 170), "ACCESS SYSTEMS  ·  azienda fittizia", font=f(14), fill=(60, 60, 60))
    dr.text((850, 110), "COPIA RIPARAZIONE", font=f(24, True), fill=(0, 0, 0), anchor="mm")
    box(dr, [420, 150, 1190, 200]); dr.line([(800, 150), (800, 200)], fill=(0, 0, 0), width=2)
    dr.text((430, 162), f"Riparazione n.     {s.riparazione_n}", font=f(24, True), fill=(0, 0, 0))
    dr.text((810, 162), f"Del        {s.data}", font=f(24, True), fill=(0, 0, 0))
    box(dr, [35, 222, 1190, 268]); dr.line([(800, 222), (800, 268)], fill=(0, 0, 0), width=2)
    dr.text((45, 235), f"Cliente    {s.cliente}", font=f(20), fill=(0, 0, 0))
    dr.text((810, 235), f"Art.  {s.articolo}", font=f(20), fill=(0, 0, 0)); dr.text((1100, 235), f"Pz. {s.pezzi}", font=f(20), fill=(0, 0, 0))
    box(dr, [35, 268, 1190, 314]); dr.line([(370, 268), (370, 314)], fill=(0, 0, 0), width=2); dr.line([(800, 268), (800, 314)], fill=(0, 0, 0), width=2)
    dr.text((45, 281), f"Ricevuto il  {s.ricevuto_il}", font=f(20), fill=(0, 0, 0))
    dr.text((380, 281), f"ddt. n.  {s.ddt_n or '/'}", font=f(20), fill=(0, 0, 0))
    dr.text((810, 281), f"del  {s.ddt_del or '/'}", font=f(20), fill=(0, 0, 0))
    box(dr, [35, 314, 1190, 610])
    tratteggio(dr, 630)
    # blocco scheda tecnico
    box(dr, [35, 650, 1190, 700]); [dr.line([(x, 650), (x, 700)], fill=(0, 0, 0), width=2) for x in (420, 800)]
    dr.text((90, 662), f"Riparazione n.  {s.riparazione_n}", font=f(24, True), fill=(0, 0, 0))
    dr.text((500, 662), f"Del   {s.data}", font=f(24, True), fill=(0, 0, 0))
    dr.text((920, 662), "Pag.   1 di 2", font=f(24, True), fill=(0, 0, 0))
    box(dr, [35, 700, 1190, 746]); dr.line([(800, 700), (800, 746)], fill=(0, 0, 0), width=2)
    dr.text((45, 710), f"Ditta:  {s.cliente}", font=f(24, True), fill=(0, 0, 0))
    dr.text((810, 710), f"Art.    {s.articolo}", font=f(24, True), fill=(0, 0, 0))
    box(dr, [35, 756, 1190, 800]); [dr.line([(x, 756), (x, 800)], fill=(0, 0, 0), width=2) for x in (360, 560)]
    dr.text((45, 768), f"Art.    {s.articolo}", font=f(20, True), fill=(0, 0, 0)); dr.text((280, 768), f"Pz. {s.pezzi}", font=f(20, True), fill=(0, 0, 0))
    dr.text((370, 768), "Prodotto il", font=f(20), fill=(0, 0, 0)); dr.text((570, 768), "Seriale", font=f(20), fill=(0, 0, 0))
    if s.prodotto_il: mano.scrivi(img, (475, 778), s.prodotto_il, 80)
    else: mano.barra(img, 480, 778, 70)
    mano.scrivi(img, (660, 778), s.seriale, 510, esatto=True)
    box(dr, [35, 800, 1190, 868]); [dr.line([(x, 800), (x, 868)], fill=(0, 0, 0), width=2) for x in (360, 620)]
    dr.text((45, 808), "Aperta - Manomessa dal cliente", font=f(18), fill=(0, 0, 0))
    dr.text((80, 838), "Si", font=f(18), fill=(0, 0, 0)); box(dr, [105, 836, 130, 861], 1)
    dr.text((190, 838), "No", font=f(18), fill=(0, 0, 0)); box(dr, [225, 836, 250, 861], 1)
    if s.aperta_manomessa is not None:
        mano.croce(img, 117 if s.aperta_manomessa else 237, 848)
    dr.text((490, 815), "Riparazione tempo", font=f(18), fill=(0, 0, 0), anchor="mm")
    if s.tempo_riparazione_min is not None:
        mano.scrivi(img, (455, 848), f"{s.tempo_riparazione_min}'", 120)
    dr.text((900, 815), "Firmware", font=f(18), fill=(0, 0, 0), anchor="mm")
    if s.firmware: mano.scrivi(img, (840, 848), s.firmware, 200, esatto=True)
    else: mano.barra(img, 850, 850, 90)
    tabella(img, dr, mano, 868, s.righe[:11], 11)
    return img


def pagina2(s, mano, rng):
    img = Image.new("RGB", (W, H), "white"); dr = ImageDraw.Draw(img)
    y = tabella(img, dr, mano, 620, s.righe[11:], 9)
    box(dr, [35, y, 1190, y + 240]); dr.text((45, y + 8), "NOTE:", font=f(20, True), fill=(0, 0, 0))
    if s.note:                                   # a capo come sulle schede reali: la prima riga parte accanto a "NOTE:"
        righe_n, x0, yy = [], 125, y + 20
        for par in s.note.split("\n"):
            parole, riga = par.split(), ""
            for p in parole:
                lim = 55 if not righe_n else 62
                if len(riga) + len(p) + 1 > lim: righe_n.append(riga); riga = p
                else: riga = (riga + " " + p).strip()
            righe_n.append(riga)
        for i, r in enumerate(righe_n[:5]):
            mano.scrivi(img, (x0 if i == 0 else 45, yy + i * 44), r, (1180 - x0) if i == 0 else 1135)
    yb = y + 270
    box(dr, [35, yb, 1190, yb + 90]); dr.line([(615, yb), (615, yb + 90)], fill=(0, 0, 0), width=2); dr.line([(35, yb + 45), (1190, yb + 45)], fill=(0, 0, 0), width=2)
    for (x, yy, t) in [(45, yb + 10, "Eseguire:"), (625, yb + 10, "Eseguito il:"), (45, yb + 55, "Per il:"), (625, yb + 55, "scaricato comp.")]:
        dr.text((x, yy), t, font=f(20, True), fill=(0, 0, 0))
    if s.eseguito_il: mano.scrivi(img, (775, yb + 24), s.eseguito_il, 380)
    return img


# ---------------------------------------------------------------- effetto scansione
def scansiona(img, rng):
    a = np.asarray(img).astype(np.float32)
    a = a * rng.uniform(0.9, 1.0) + rng.uniform(0, 15)                        # carta non bianca
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    img = img.rotate(rng.uniform(-1.5, 1.5), resample=Image.BICUBIC, fillcolor=(245, 245, 245),
                     translate=(rng.uniform(-12, 12), rng.uniform(-12, 12)))
    if rng.random() < .6:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
    a = np.asarray(img).astype(np.float32)
    a += rng.normal(0, rng.uniform(3, 9), a.shape)                              # rumore del sensore
    if rng.random() < .5:                                                       # puntini di polvere
        for _ in range(int(rng.integers(20, 200))):
            y, x = int(rng.integers(0, H)), int(rng.integers(0, W)); a[y:y + 2, x:x + 2] = rng.uniform(40, 120)
    if rng.random() < .5:                                                       # riga verticale dello scanner
        x = int(rng.integers(0, W)); a[:, x:x + 1] *= rng.uniform(0.7, 0.9)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if rng.random() < .4:
        img = img.convert("L").convert("RGB")                                   # scansione in grigio
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=int(rng.integers(55, 90)))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def verita(s):
    d = asdict(s)
    d["righe"] = [asdict(r) for r in s.righe]
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(QUI, "..", "data", "sintetici"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--png", action="store_true", help="salva anche le pagine in PNG")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    for i in range(args.n):
        s = campiona_scheda(rng, i)
        mano = Mano(rng)
        pagine = [scansiona(pagina1(s, mano, rng), rng), scansiona(pagina2(s, mano, rng), rng)]
        base = os.path.join(args.out, s.doc_id)
        pagine[0].save(base + ".pdf", "PDF", resolution=150, save_all=True, append_images=pagine[1:])
        if args.png:
            for k, p in enumerate(pagine, 1):
                p.save(f"{base}_p{k}.png")
        json.dump(verita(s), open(base + ".json", "w"), ensure_ascii=False, indent=2)
    print(f"{args.n} schede in {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
