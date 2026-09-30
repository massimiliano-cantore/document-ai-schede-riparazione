"""Seconda lettura mirata dei campi liberi: ritaglio ingrandito di ogni campo, letto due volte
con ritagli diversi. Da incollare in una cella Kaggle (GPU T4 x2, Internet On, dataset schede-sintetiche-kyros)."""
import glob, json, os, re, time, subprocess
subprocess.run("pip install -q -U 'transformers>=4.49' accelerate qwen-vl-utils", shell=True)
import torch
from PIL import Image
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info

PAGINE = {os.path.basename(f)[:-4]: f for f in glob.glob('/kaggle/input/**/pagine/*.jpg', recursive=True)}
schede = sorted({k[:9] for k in PAGINE})
# riquadri del modulo (pixel a 150 dpi, pagina 1240x1754) con margine per le piccole rotazioni della scansione
CAMPI = {
    'prodotto_il': (1, (355, 745, 570, 810), "la data scritta a mano dopo 'Prodotto il' (formato mm/aaaa)"),
    'seriale': (1, (555, 745, 1200, 810), "il numero seriale scritto a mano dopo 'Seriale' (6 cifre, oppure 4 cifre / 4 cifre)"),
    'tempo_riparazione_min': (1, (355, 795, 630, 875), "il tempo di riparazione scritto a mano (minuti, es. 30')"),
    'firmware': (1, (610, 795, 1200, 875), "la versione firmware scritta a mano (es. V17)"),
    'eseguito_il': (2, (600, 1440, 1200, 1540), "la data scritta a mano dopo 'Eseguito il' (formato gg/mm/aaaa)"),
}
if 'model' not in globals():   # non ricaricare il modello se la cella viene rilanciata
    MOD = 'Qwen/Qwen2.5-VL-7B-Instruct'
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(MOD, torch_dtype=torch.float16, device_map='auto')
    processor = AutoProcessor.from_pretrained(MOD)

def leggi(img, cosa):
    testo_prompt = (f"Leggi {cosa}. Rispondi solo con il valore, senza altro testo. "
                    "Rispondi VUOTO solo se nel riquadro non c'è nulla scritto a mano oppure solo '/' o un trattino.")
    msg = [{'role': 'user', 'content': [{'type': 'image', 'image': img}, {'type': 'text', 'text': testo_prompt}]}]
    t = processor.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    im, vid = process_vision_info(msg)
    inp = processor(text=[t], images=im, videos=vid, return_tensors='pt').to(model.device)
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=20, do_sample=False)
    return processor.batch_decode(out[:, inp.input_ids.shape[1]:], skip_special_tokens=True)[0].strip()

OUT = '/kaggle/working/campi_qwen.jsonl'
fatti = {json.loads(l)['doc_id'] for l in open(OUT)} if os.path.exists(OUT) else set()
N = int(os.environ.get('N_SCHEDE', 100))
with open(OUT, 'a') as f:
    for i, d in enumerate(schede[:N]):
        if d in fatti: continue
        t0 = time.time(); rec = {'doc_id': d, 'letture': {}}
        pag = {k: Image.open(PAGINE[f'{d}_p{k}']).convert('RGB') for k in (1, 2)}
        for campo, (p, (x0, y0, x1, y1), cosa) in CAMPI.items():
            letture = []
            for scala, (mx, my) in ((2, (10, 20)), (3, (25, 35))):          # due ritagli diversi = due letture indipendenti
                c = pag[p].crop((x0 - mx, y0 - my, x1 + mx, y1 + my))   # margine verticale ampio: la scansione sposta il modulo
                letture.append(leggi(c.resize((c.width * scala, c.height * scala), Image.LANCZOS), cosa))
            rec['letture'][campo] = letture
        rec['secondi'] = round(time.time() - t0, 1)
        f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush()
        print(i, d, rec['secondi'], 's', {k: v for k, v in rec['letture'].items()})
print('FINITO: scarica /kaggle/working/campi_qwen.jsonl')
