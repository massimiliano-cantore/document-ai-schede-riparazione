"""Fine-tuning QLoRA di Qwen2.5-VL-7B sulle schede sintetiche (Kaggle, 1 GPU T4, gratuito).

Tre fasi (variabile FASE), tutte nello stesso notebook:
  FASE=genera -> genera N schede sintetiche di ADDESTRAMENTO (semi 2001+, diversi dal test) con la banca inchiostro
                 privata e le prepara in /kaggle/working/train_ds   (CPU, ~15 min)
  FASE=train  -> addestra gli adattatori LoRA e li salva in /kaggle/working/lora_schede
  FASE=test   -> legge le 100 schede di test con il modello addestrato -> /kaggle/working/predizioni_ft.jsonl
Input Kaggle: dataset privato kyros-finetune (questo pacchetto) e, per il test, schede-sintetiche-kyros-v2.
"""
import glob, json, os, re, subprocess, sys, time
from PIL import Image

FASE = os.environ.get("FASE", "train")
PKG = os.path.dirname(glob.glob("/kaggle/input/**/prepara_train.py", recursive=True)[0])
N_TRAIN = int(os.environ.get("N_TRAIN", 800))          # quante schede di addestramento
LATO = (896, 1267)                                        # stessa risoluzione in addestramento e test
LORA = "/kaggle/working/lora_schede"


def trova(nome):
    f = glob.glob(f"/kaggle/working/**/{nome}", recursive=True) + glob.glob(f"/kaggle/input/**/{nome}", recursive=True)
    return f[0] if f else None


if FASE == "genera":
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "Hershey-Fonts"], check=True)
    N = int(os.environ.get("N_TRAIN", 800)); blocchi = 8; per = -(-N // blocchi)
    env = dict(os.environ, DOCAI_BANCA=f"{PKG}/banca")
    proc = [subprocess.Popen([sys.executable, f"{PKG}/generator/genera_schede.py", "--n", str(per), "--png",
                              "--seed", str(2001 + b), "--out", f"/kaggle/working/raw/b{b}"], env=env,
                             stdout=subprocess.DEVNULL) for b in range(blocchi)]
    for p in proc: p.wait()
    cartelle = sorted(glob.glob("/kaggle/working/raw/b*"))
    subprocess.run([sys.executable, f"{PKG}/prepara_train.py", *cartelle, "--out", "/kaggle/working/train_ds"], check=True)
    subprocess.run("rm -rf /kaggle/working/raw", shell=True)
    print("pronto: /kaggle/working/train_ds"); raise SystemExit

from unsloth import FastVisionModel, is_bf16_supported   # unsloth prima di torch/transformers (kernel appena riavviato)
import torch


ns = {}; exec(open(f"{PKG}/estrazione/prompt.py").read(), ns); PROMPT = ns["PROMPT"]


def pagina(p):
    return Image.open(p).convert("RGB").resize(LATO, Image.LANCZOS)


def messaggi(immagini, risposta=None):
    m = [{"role": "user", "content": [{"type": "image", "image": immagini[0]}, {"type": "image", "image": immagini[1]},
                                      {"type": "text", "text": PROMPT}]}]
    if risposta is not None:
        m.append({"role": "assistant", "content": [{"type": "text", "text": risposta}]})
    return {"messages": m}


if FASE == "train":
    from trl import SFTTrainer, SFTConfig
    from unsloth.trainer import UnslothVisionDataCollator

    TRAIN = trova("train.jsonl"); BASE = os.path.dirname(TRAIN)
    esempi = [json.loads(l) for l in open(TRAIN)][:N_TRAIN]
    print(len(esempi), "esempi da", BASE)

    class Schede(torch.utils.data.Dataset):          # immagini aperte al volo: in RAM non ci starebbero tutte
        def __len__(self): return len(esempi)
        def __getitem__(self, i):
            e = esempi[i]
            return messaggi([pagina(f"{BASE}/{p}") for p in e["pagine"]], e["risposta"])

    model, tok = FastVisionModel.from_pretrained("unsloth/Qwen2.5-VL-7B-Instruct-unsloth-bnb-4bit", load_in_4bit=True,
                                                 use_gradient_checkpointing="unsloth")
    model = FastVisionModel.get_peft_model(
        model, finetune_vision_layers=os.environ.get("VISIONE", "1") == "1",   # la grafia si impara anche nella parte visiva
        finetune_language_layers=True, finetune_attention_modules=True, finetune_mlp_modules=True,
        r=16, lora_alpha=16, lora_dropout=0, bias="none", random_state=3407)
    FastVisionModel.for_training(model)
    trainer = SFTTrainer(
        model=model, tokenizer=tok, data_collator=UnslothVisionDataCollator(model, tok, resize="max", max_seq_length=6144), train_dataset=Schede(),  # resize max: NON ridurre a 512 px
        args=SFTConfig(
            per_device_train_batch_size=1, gradient_accumulation_steps=4, warmup_steps=10, num_train_epochs=1,
            learning_rate=2e-4, fp16=not is_bf16_supported(), bf16=is_bf16_supported(), logging_steps=5,
            optim="adamw_8bit", weight_decay=0.01, lr_scheduler_type="linear", seed=3407,
            output_dir="/kaggle/working/ckpt", save_steps=25, save_total_limit=2, report_to="none",
            remove_unused_columns=False, dataset_text_field="", dataset_kwargs={"skip_prepare_dataset": True},
            max_length=6144))
    t = time.time()
    stats = trainer.train(resume_from_checkpoint=os.environ.get("RIPRENDI") == "1")
    model.save_pretrained(LORA); tok.save_pretrained(LORA)
    json.dump({"esempi": len(esempi), "ore": round((time.time() - t) / 3600, 2), "loss_finale": stats.training_loss,
               "log": trainer.state.log_history}, open("/kaggle/working/addestramento.json", "w"), indent=1)
    print("salvato", LORA, f"{(time.time() - t) / 3600:.1f} ore")

if FASE == "test" or (FASE == "train" and os.environ.get("TEST_DOPO") == "1"):
    if FASE == "test":   # modello addestrato in una sessione precedente (o MODELLO=base per il confronto)
        sorgente = os.environ.get("MODELLO", LORA if os.path.isdir(LORA) else os.path.dirname(trova("adapter_config.json")))
        if sorgente == "base": sorgente = "unsloth/Qwen2.5-VL-7B-Instruct-unsloth-bnb-4bit"
        model, tok = FastVisionModel.from_pretrained(sorgente, load_in_4bit=True)
    else:
        sorgente = "modello appena addestrato"
    FastVisionModel.for_inference(model)
    PAG = {os.path.basename(f)[:-4]: f for f in glob.glob("/kaggle/input/**/pagine/SYN-*.jpg", recursive=True)}
    schede = sorted({k[:9] for k in PAG})[:int(os.environ.get("N_SCHEDE", 100))]
    OUT = "/kaggle/working/predizioni_ft.jsonl"
    fatti = {json.loads(l)["doc_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    print(sorgente, len(schede), "schede di test")
    with open(OUT, "a") as f:
        for i, d in enumerate(schede):
            if d in fatti: continue
            imm = [pagina(PAG[f"{d}_p{k}"]) for k in (1, 2)]
            testo = tok.apply_chat_template(messaggi(imm)["messages"], add_generation_prompt=True)
            inp = tok(imm, testo, add_special_tokens=False, return_tensors="pt").to("cuda")
            t = time.time()
            with torch.no_grad():
                out = model.generate(**inp, max_new_tokens=1500, do_sample=False, use_cache=True)
            g = tok.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]
            m = re.search(r"\{.*\}", g, re.S)
            try: pred = json.loads(m.group()) if m else None
            except json.JSONDecodeError: pred = None
            f.write(json.dumps({"doc_id": d, "pred": pred, "grezzo": g, "secondi": round(time.time() - t, 1), "costo_usd": 0},
                               ensure_ascii=False) + "\n"); f.flush()
            print(i, d, f"{time.time() - t:.0f}s", "ok" if pred else "JSON non valido")
