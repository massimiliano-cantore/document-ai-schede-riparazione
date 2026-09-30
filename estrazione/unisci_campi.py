"""Unisce la lettura della pagina intera con le due letture dei ritagli ingranditi.

Per ogni campo libero: si scartano le letture che non rispettano il formato (seriale, date, V..),
si prende il valore più votato; se le letture valide non sono tutte uguali il campo va in campi_incerti.
Uso: python unisci_campi.py predizioni_corrette.jsonl campi_qwen.jsonl uscita.jsonl
"""
import json, re, sys
from collections import Counter
from schema import norm

FORMATI = {
    'seriale': r'^(\d{6}|\d{4}/\d{4})$',
    'prodotto_il': r'^\d{2}/\d{4}$',
    'eseguito_il': r'^\d{2}/\d{2}/\d{4}$',
    'firmware': r'^V\d{1,2}(\.\d)?$',
    'tempo_riparazione_min': r'^\d{1,3}$',
}


def pulisci(campo, v):
    if v is None: return None
    s = str(v).upper().strip().strip('.').replace(' ', '')
    if s in ('VUOTO', '', '/', '-', 'NULL', 'NONE'): return None
    if campo == 'seriale':
        s = s.translate(str.maketrans('OQDIL|SBZG', '0001115826'))    # confusioni tipiche lettera/cifra
    if campo == 'tempo_riparazione_min':
        m = re.search(r'\d+', s); return int(m.group()) if m else None
    if campo == 'firmware':
        s = 'V' + s.lstrip('VU').translate(str.maketrans('OIL', '011'))
    if campo in ('prodotto_il', 'eseguito_il'):
        s = s.translate(str.maketrans('OIL', '011'))
    return norm(s, campo)


def valido(campo, v):
    return v is None or bool(re.match(FORMATI[campo], str(v)))


def scegli(campo, candidati):
    val = [c for c in candidati if valido(campo, c)] or candidati
    voti = Counter(json.dumps(c) for c in val)
    migliore, n = voti.most_common(1)[0]
    unanime = len(set(json.dumps(c) for c in candidati)) == 1
    return json.loads(migliore), unanime


def main(pred_f, campi_f, out_f):
    campi = {json.loads(l)['doc_id']: json.loads(l)['letture'] for l in open(campi_f)}
    with open(out_f, 'w') as f:
        for l in open(pred_f):
            r = json.loads(l); p = r.get('pred') or {}
            lett = campi.get(r['doc_id'])
            if lett:
                inc = set(p.get('campi_incerti') or [])
                for campo in FORMATI:
                    cand = [pulisci(campo, p.get(campo))] + [pulisci(campo, x) for x in lett.get(campo, [])]
                    v, unanime = scegli(campo, cand)
                    p[campo] = v
                    (inc.discard if unanime else inc.add)(campo)
                p['campi_incerti'] = sorted(inc); r['pred'] = p
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main(*sys.argv[1:4])
