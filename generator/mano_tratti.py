"""Scrittura a mano simulata a tratti (penna a sfera), invece che con un font.

Ogni carattere parte dai tratti di un font a linea singola (Hershey) e viene deformato:
inclinazione e larghezza della persona, variazione di dimensione e rotazione per lettera,
linea di base che ondeggia, tremolio lungo il tratto, pressione variabile, inchiostro non uniforme.
"""
import numpy as np
from HersheyFonts import HersheyFonts
from PIL import Image, ImageDraw

_FONT_CACHE = {}


def _font(name):
    if name not in _FONT_CACHE:
        h = HersheyFonts(); h.load_default_font(name); h.normalize_rendering(100)   # altezza maiuscole ~100
        _FONT_CACHE[name] = h
    return _FONT_CACHE[name]


def _smooth_noise(n, rng, scale, corr):
    """Rumore correlato lungo un tratto (random walk filtrato)."""
    w = rng.normal(0, 1, n + corr)
    k = np.ones(corr) / corr
    return np.convolve(w, k, mode="valid")[:n] * scale


def _resample(poly, step):
    p = np.asarray(poly, float)
    if len(p) < 2:
        return p
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    L = np.concatenate([[0], np.cumsum(seg)])
    if L[-1] == 0:
        return p
    t = np.linspace(0, L[-1], max(2, int(L[-1] / step) + 1))
    return np.stack([np.interp(t, L, p[:, 0]), np.interp(t, L, p[:, 1])], 1)


class Scrittore:
    """Una persona: stile costante nel documento, variazioni a ogni lettera."""

    def __init__(self, rng):
        self.rng = rng
        self.maiuscolo = rng.random() < 0.75
        self.font = str(rng.choice(["futural", "futural", "rowmans"]))
        self.slant = rng.uniform(-0.25, 0.15)            # shear orizzontale
        self.larghezza = rng.uniform(0.8, 1.15)
        self.spaziatura = rng.uniform(1.2, 1.9)
        self.tremolio = rng.uniform(1.0, 2.2)
        self.spessore = rng.uniform(1.2, 1.9)
        self.altezza = rng.uniform(27, 36)              # px a 150 dpi (≈ 4-5 mm)
        blu = rng.random() < 0.75
        self.colore = np.array([rng.integers(15, 45), rng.integers(35, 80), rng.integers(130, 185)] if blu else [25, 25, 35])

    def _strokes_char(self, ch):
        h = _font(self.font)
        return [[(x, -y) for x, y in s] for s in h.strokes_for_text(ch)]   # Hershey ha y verso l'alto

    def rendi(self, testo, altezza=None, colore=None):
        """Ritorna un'immagine RGBA con il testo scritto (sfondo trasparente)."""
        rng, S = self.rng, 2                                                    # supersampling 2x
        H0 = (altezza or self.altezza) * S / 100.0                              # fattore di scala
        tratti, x = [], 0.0
        drift = _smooth_noise(len(testo) + 1, rng, 6, 3)                        # linea di base ondulata
        for i, ch in enumerate(testo):
            if ch == " ":
                x += 45 * self.spaziatura; continue
            st = self._strokes_char(ch)
            if not st:
                x += 40; continue
            allp = np.concatenate([np.asarray(s, float) for s in st])
            x0, x1 = allp[:, 0].min(), allp[:, 0].max()
            sc = rng.normal(1, 0.10); rot = rng.normal(0, 0.07)
            ca, sa = np.cos(rot), np.sin(rot)
            cx = (x0 + x1) / 2
            for s in st:
                p = _resample(s, 3.0)
                p[:, 0] = (p[:, 0] - cx) * self.larghezza
                p = p * sc
                p = p @ np.array([[ca, -sa], [sa, ca]])
                p[:, 0] += p[:, 1] * -self.slant                               # inclinazione (y verso il basso)
                n = len(p)
                p[:, 0] += _smooth_noise(n, rng, 1.8 * self.tremolio, 5)
                p[:, 1] += _smooth_noise(n, rng, 1.8 * self.tremolio, 5)
                p[:, 0] += x + (x1 - x0) * self.larghezza * sc / 2
                p[:, 1] += drift[i]
                tratti.append(p)
            x += ((x1 - x0) * self.larghezza * sc + 14 * self.spaziatura) + rng.normal(0, 3)
        if not tratti:
            return Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        allp = np.concatenate(tratti)
        mn, mx = allp.min(0) - 20, allp.max(0) + 20
        wpx, hpx = int((mx[0] - mn[0]) * H0) + 8, int((mx[1] - mn[1]) * H0) + 8
        img = Image.new("RGBA", (max(wpx, 4), max(hpx, 4)), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        col = self.colore if colore is None else np.array(colore)
        for p in tratti:
            q = (p - mn) * H0
            pressione = np.clip(1 + _smooth_noise(len(q), rng, 0.25, 8), 0.55, 1.4)
            for k in range(len(q) - 1):
                w = max(1, int(round(self.spessore * S * pressione[k])))
                a = int(np.clip(rng.normal(225, 20), 150, 255))                   # inchiostro non uniforme
                dr.line([tuple(q[k]), tuple(q[k + 1])], fill=tuple(int(c) for c in col) + (a,), width=w)
        return img.resize((max(1, img.width // S), max(1, img.height // S)), Image.LANCZOS)
