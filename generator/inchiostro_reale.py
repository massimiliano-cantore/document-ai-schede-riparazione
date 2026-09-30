"""Scrittura a mano da inchiostro reale: parole e caratteri ritagliati da schede compilate a mano.

La banca (immagini) è PRIVATA e non è nel repository: percorso in DOCAI_BANCA (cartella con
banca_parole.json, banca_glifi.json, parole/, glifi/). Se manca si usa mano_tratti come ripiego.
"""
import json, os
import numpy as np
from PIL import Image

BANCA = os.getenv("DOCAI_BANCA", os.path.join(os.path.dirname(__file__), "..", "privato"))
SCALA = 150 / 200                                   # ritagli a 200 dpi, schede a 150 dpi


def disponibile():
    return os.path.exists(os.path.join(BANCA, "banca_parole.json"))


class Inchiostro:
    def __init__(self, rng, colore):
        self.rng, self.colore = rng, np.array(colore)
        self.parole = json.load(open(os.path.join(BANCA, "banca_parole.json")))
        self.glifi = json.load(open(os.path.join(BANCA, "banca_glifi.json")))
        tutti = sorted({e["w"] for v in self.parole.values() for e in v})
        self.scrittore = str(rng.choice(tutti))       # una persona per scheda, quando possibile
        self.cache = {}

    def _scegli(self, lista):
        mie = [e for e in lista if e["w"] == self.scrittore]
        return (mie or lista)[int(self.rng.integers(len(mie or lista)))]

    def _alpha(self, file, glifo=False):
        if file not in self.cache:
            g = np.array(Image.open(os.path.join(BANCA, file)).convert("L")).astype(float)
            a = np.clip(g * 1.4, 0, 255) if glifo else np.clip((240 - g) * 2.0, 0, 255)
            self.cache[file] = a
        return self.cache[file]

    def _rgba(self, a):
        a = np.clip(a * self.rng.uniform(0.85, 1.05), 0, 255).astype(np.uint8)
        h, w = a.shape
        rgb = np.broadcast_to(self.colore.astype(np.uint8), (h, w, 3))
        im = Image.fromarray(np.dstack([rgb, a]), "RGBA")
        return im.resize((max(1, int(w * SCALA)), max(1, int(h * SCALA))), Image.LANCZOS)

    def _parola(self, t):
        im = self._token(t) or self._token(t.upper())
        if im is None and len(t) > 1 and t[-1] in ".,":          # "ROTTA," = parola vera + segno disegnato
            base = self._parola(t[:-1])
            if base is not None:
                a, _ = self._segno(t[-1]); m = self._rgba(a)
                out = Image.new("RGBA", (base.width + m.width + 2, max(base.height, m.height)), (0, 0, 0, 0))
                out.alpha_composite(base, (0, out.height - base.height)); out.alpha_composite(m, (base.width + 2, out.height - m.height))
                return out
        return im

    def _segno(self, c):
        """'-', '.', ':' non sono nella banca: tratto di penna disegnato."""
        from PIL import ImageDraw
        h = 40; im = Image.new("L", (26 if c == "-" else 10, h), 0); d = ImageDraw.Draw(im)
        j = lambda: float(self.rng.normal(0, 1))
        if c == "-": d.line([(2, 24 + j()), (22 + 2 * j(), 22 + j())], fill=int(self.rng.integers(170, 230)), width=3)
        elif c == ",":
            d.line([(6, 32), (3, 40)], fill=int(self.rng.integers(170, 230)), width=3)
        else:
            for yy in ([34] if c == "." else [16, 34]): d.ellipse([3, yy - 2, 7, yy + 2], fill=int(self.rng.integers(170, 230)))
        return np.array(im, float) / 0.75, 0

    def _token(self, t):
        if t in self.parole:
            return self._rgba(self._alpha(self._scegli(self.parole[t])["file"]))
        if not all(c in self.glifi or c in "-.:," for c in t):
            return None
        ims = []
        for c in t:
            if c in "-.:,":
                a, dy = self._segno(c); ims.append((self._rgba(a), dy)); continue
            p = self._scegli(self.glifi[c])
            ims.append((self._rgba(self._alpha(p["file"], True)), int(p["dy"] * SCALA)))
        H = max(im.height + dy for im, dy in ims) + 4
        gap = int(self.rng.integers(2, 6))
        W = sum(im.width for im, _ in ims) + gap * len(ims)
        out, x = Image.new("RGBA", (W, H), (0, 0, 0, 0)), 0
        for im, dy in ims:
            out.alpha_composite(im, (x, H - 2 - dy - im.height)); x += im.width + gap
        return out

    def rendi(self, testo, ripiego):
        """Immagine RGBA del testo; i token mancanti nella banca vengono scritti da `ripiego(token)`."""
        pezzi = []
        for t in testo.split():
            im = self._parola(t)
            pezzi.append(im if im is not None else ripiego(t))
        if not pezzi:
            return None
        sp = int(self.rng.integers(10, 18))
        H = max(p.height for p in pezzi)
        out, x = Image.new("RGBA", (sum(p.width for p in pezzi) + sp * len(pezzi), H), (0, 0, 0, 0)), 0
        for p in pezzi:
            out.alpha_composite(p, (x, (H - p.height) // 2)); x += p.width + sp
        return out
