"""Confronto: stessa estrazione della tappa 2, ma con Claude via API (Haiku 4.5 / Sonnet 5).

Stesse 100 schede sintetiche, stesso prompt, stesso formato di uscita e stessa valutazione di Qwen.
Su Kaggle: Add-ons -> Secrets -> ANTHROPIC_API_KEY (agganciato al notebook). Internet: ON. Niente GPU.
    %env MODELLO_CLAUDE=claude-haiku-4-5-20251001     (oppure claude-sonnet-5)
    poi incollare questo file in una cella e lanciarla; scaricare predizioni_<modello>.jsonl dall'Output
"""
import subprocess; subprocess.run("pip install -q -U anthropic json_repair", shell=True)
import base64, glob, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor

DATI = os.path.dirname(glob.glob('/kaggle/input/**/schema.py', recursive=True)[0])
VERITA = os.path.dirname(glob.glob('/kaggle/input/**/verita/*.json', recursive=True)[0])
PAGINE = {os.path.basename(f)[:-4]: f for f in glob.glob('/kaggle/input/**/pagine/*.jpg', recursive=True)}
sys.path.insert(0, DATI)
from prompt import PROMPT
schede = sorted({k[:9] for k in PAGINE})

import anthropic
try:
    from kaggle_secrets import UserSecretsClient
    os.environ.setdefault('ANTHROPIC_API_KEY', UserSecretsClient().get_secret('ANTHROPIC_API_KEY'))
except Exception:
    pass
client = anthropic.Anthropic(max_retries=5)

MODELLO = os.environ.get('MODELLO_CLAUDE', 'claude-haiku-4-5-20251001')
PREZZI = {  # dollari per milione di token (input, output) - verificare sul listino ufficiale
    'claude-haiku-4-5-20251001': (1, 5), 'claude-sonnet-5': (2, 10), 'claude-opus-5-5': (4, 20)}
p_in, p_out = PREZZI.get(MODELLO, (0, 0))
N = int(os.environ.get('N_SCHEDE', 100))
nome = MODELLO.split('-')[1]          # haiku / sonnet / opus
OUT = f'/kaggle/working/predizioni_{nome}.jsonl'
print(MODELLO, len(schede), 'schede ->', OUT)


def estrai_json(testo):
    m = re.search(r'\{.*\}', testo, re.S)
    if not m: return None
    try: return json.loads(m.group())
    except json.JSONDecodeError: return None


def leggi(doc_id):
    contenuto = []
    for k in (1, 2):
        dati = base64.standard_b64encode(open(PAGINE[f'{doc_id}_p{k}'], 'rb').read()).decode()
        contenuto.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': dati}})
    contenuto.append({'type': 'text', 'text': PROMPT + '\nRispondi solo con il JSON.'})
    t = time.time()
    r = client.messages.create(model=MODELLO, max_tokens=4000,
                               messages=[{'role': 'user', 'content': contenuto}])
    grezzo = ''.join(b.text for b in r.content if b.type == 'text')
    costo = (r.usage.input_tokens * p_in + r.usage.output_tokens * p_out) / 1e6
    return {'doc_id': doc_id, 'pred': estrai_json(grezzo), 'grezzo': grezzo, 'secondi': round(time.time() - t, 1),
            'token_in': r.usage.input_tokens, 'token_out': r.usage.output_tokens, 'costo_usd': round(costo, 5)}


fatti = {json.loads(l)['doc_id'] for l in open(OUT)} if os.path.exists(OUT) else set()
da_fare = [d for d in schede[:N] if d not in fatti]
with open(OUT, 'a') as f, ThreadPoolExecutor(4) as pool:   # 4 richieste in parallelo
    for i, r in enumerate(pool.map(leggi, da_fare)):
        f.write(json.dumps(r, ensure_ascii=False) + '\n'); f.flush()
        print(i, r['doc_id'], f"{r['secondi']}s ${r['costo_usd']:.4f}")

righe = [json.loads(l) for l in open(OUT)]
print(f"\n{MODELLO}: {len(righe)} schede, costo totale ${sum(r['costo_usd'] for r in righe):.2f}, "
      f"token in medi {sum(r['token_in'] for r in righe) / len(righe):.0f}, out {sum(r['token_out'] for r in righe) / len(righe):.0f}, "
      f"JSON non validi {sum(r['pred'] is None for r in righe)}")

# la valutazione (stessa di Qwen) si fa poi in locale con valuta.py / correggi.py
