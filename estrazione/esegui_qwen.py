"""Tappa 2: estrazione con Qwen2.5-VL-7B su Kaggle (GPU T4 x2) + valutazione."""
import subprocess; subprocess.run("pip install -q -U 'transformers>=4.49' accelerate qwen-vl-utils", shell=True)
import glob, json, os, re, sys, time
# il dataset può essere estratto in una o più sottocartelle: cerco i file ovunque sotto /kaggle/input
DATI = os.path.dirname(glob.glob('/kaggle/input/**/schema.py', recursive=True)[0])
VERITA = os.path.dirname(glob.glob('/kaggle/input/**/verita/*.json', recursive=True)[0])
PAGINE = {os.path.basename(f)[:-4]: f for f in glob.glob('/kaggle/input/**/pagine/*.jpg', recursive=True)}
sys.path.insert(0, DATI)
from prompt import PROMPT
schede = sorted({k[:9] for k in PAGINE})
print(DATI, len(schede), 'schede')

import torch
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
MODELLO = 'Qwen/Qwen2.5-VL-7B-Instruct'
if 'model' not in globals():
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(MODELLO, torch_dtype=torch.float16, device_map='auto')
PIX = 1600 * 28 * 28   # risoluzione per pagina: abbastanza per leggere la scrittura a mano
processor = AutoProcessor.from_pretrained(MODELLO, min_pixels=256 * 28 * 28, max_pixels=PIX)

def estrai_json(testo):
    m = re.search(r'\{.*\}', testo, re.S)
    if not m: return None
    try: return json.loads(m.group())
    except json.JSONDecodeError: return None

def leggi(doc_id):
    contenuto = [{'type': 'image', 'image': 'file://' + PAGINE[f'{doc_id}_p{k}']} for k in (1, 2)]
    contenuto.append({'type': 'text', 'text': PROMPT})
    msg = [{'role': 'user', 'content': contenuto}]
    testo = processor.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    img, vid = process_vision_info(msg)
    inp = processor(text=[testo], images=img, videos=vid, return_tensors='pt').to(model.device)
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=1200, do_sample=False)
    return processor.batch_decode(out[:, inp.input_ids.shape[1]:], skip_special_tokens=True)[0]



N = int(os.environ.get('N_SCHEDE', 100))
OUT = '/kaggle/working/predizioni_qwen.jsonl'
fatti = {json.loads(l)['doc_id'] for l in open(OUT)} if os.path.exists(OUT) else set()
with open(OUT, 'a') as f:
    for i, d in enumerate(schede[:N]):
        if d in fatti: continue
        t = time.time(); grezzo = leggi(d); dt = time.time() - t
        f.write(json.dumps({'doc_id': d, 'pred': estrai_json(grezzo), 'grezzo': grezzo, 'secondi': round(dt, 1), 'costo_usd': 0}, ensure_ascii=False) + '\n'); f.flush()
        print(i, d, f'{dt:.0f}s')

subprocess.run(f'cd {DATI} && python valuta.py --verita {VERITA} --pred /kaggle/working/predizioni_qwen.jsonl --out /kaggle/working/report_qwen.json', shell=True)

from schema import STAMPATI, A_MANO, RIGA, uguali
err = []
for l in open(OUT):
    r = json.loads(l); v = json.load(open(f"{VERITA}/{r['doc_id']}.json")); p = r['pred'] or {}
    for c in A_MANO:
        if not uguali(p.get(c), v.get(c), c): err.append((r['doc_id'], c, v.get(c), p.get(c)))
    for i, rv in enumerate(v['righe']):
        rp = (p.get('righe') or [{}] * 99)[i] if i < len(p.get('righe') or []) else {}
        for c in RIGA:
            if not uguali(rp.get(c), rv.get(c), c): err.append((r['doc_id'], f'righe[{i}].{c}', rv.get(c), rp.get(c)))
import pandas as pd
df = pd.DataFrame(err, columns=['scheda', 'campo', 'vero', 'letto'])
print(df['campo'].str.replace(r'\[\d+\]', '', regex=True).value_counts().head(15))
df.to_csv('/kaggle/working/errori_qwen.csv', index=False); print(df.head(40).to_string())