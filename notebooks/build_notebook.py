"""Generates notebooks/kaggle_train.ipynb. Edit the cells here, then run:

    python notebooks/build_notebook.py
"""

import json
from pathlib import Path

CELLS = [
    ("markdown", """# Humanity-First AI: training run on Kaggle (milestone M3)

**What this notebook does, in plain language.** It trains *our own* language model from scratch, on Kaggle's free GPUs, using only openly licensed, human-written text. Nothing here uses an existing AI model.

1. Gets the project's code from GitHub and runs a quick self-test.
2. Checks the hardware (it needs **two T4 GPUs**) and does a one-minute training test on the GPU.
3. **Checks the data sources** (Common Pile, Common Corpus, Wikipedia) are what our code expects. This is the first time they are checked, because the development computer cannot reach them. If anything is unexpected, it stops and tells you why.
4. Downloads about 5 GB of openly licensed text in about 30 languages and cleans it.
5. Trains a multilingual tokenizer (the tool that splits text into pieces) and measures how well it covers each language.
6. Trains the model (about 26 million parameters) on both GPUs, for up to 7 hours.
7. Writes a **report card**: did it learn, what text does it write, how long did it take, how much energy did it use.

**Expected cost:** about 8–10 hours in total, of which about 7 are GPU time, inside Kaggle's free weekly quota of about 30 hours. Energy: roughly 1–2 kWh (two 70 W GPUs plus the host computer), which is Kaggle's electricity, not yours. The report gives the real number.

**What to expect from the model (honestly):** mostly grammatical sentences that drift off topic and are often factually wrong. It will not answer questions or reason. That is normal at this size; facts will come from the cited library search (milestone M5).

### How to run it
1. On kaggle.com: **Create → New Notebook → File → Import Notebook**, and choose this file.
2. In the right-hand panel, **Session options**: Accelerator **GPU T4 x2**; **Internet on** (needs a phone-verified account).
3. Click **Save Version → Save & Run All (Commit) → Save**. It runs in the background; you can close the browser.
4. When it finishes, open the version, go to **Output**, and download `outputs/report.md` (plus anything else you like). Paste the report into our chat.

If a step fails, copy the error message into the chat. Every step prints what it is doing."""),
    ("code", """# Settings. Normally you do not need to change anything here.
DRY_RUN = False        # True: a quick test of the whole flow on the CPU, with small public-domain books
BRANCH = "main"        # falls back to the development branch if main does not have this code yet"""),
    ("markdown", "## 1. Get the code and run a quick self-test"),
    ("code", """import os, subprocess, sys
REPO = "https://github.com/MarcGRusty/humanity-first-ai"
WORK = "/kaggle/working" if os.path.exists("/kaggle/working") else os.path.abspath("kaggle-run")
CODE = "/tmp/humanity-first-ai"
os.makedirs(WORK, exist_ok=True)
if not os.path.exists(os.path.join(CODE, "src", "hfai", "kaggle.py")):
    for branch in (BRANCH, "claude/wonderful-pascal-dtl1pr"):
        subprocess.run(["rm", "-rf", CODE])
        cloned = subprocess.run(["git", "clone", "--depth", "1", "--branch", branch, REPO, CODE]).returncode == 0
        if cloned and os.path.exists(os.path.join(CODE, "src", "hfai", "kaggle.py")):
            print("Using branch:", branch)
            break
    else:
        raise SystemExit("Could not get the code from GitHub. Is Internet switched on in the session options?")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", CODE + "[dev]"], check=True)
sys.path.insert(0, os.path.join(CODE, "src"))
tests = ["tests/test_tokenizer.py", "tests/test_rules_language.py", "tests/test_model_training.py"]
subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", *tests, "-k", "not two_process"], cwd=CODE, check=True)
print("Self-test passed.")"""),
    ("markdown", "## 2. Check the hardware"),
    ("code", """from hfai.kaggle import check_hardware, gpu_smoke_test
from pathlib import Path
hardware = check_hardware(require_gpu=not DRY_RUN)
print(hardware)
GPUS = len(hardware["gpus"])
print("GPU smoke test (a minute of real mixed-precision training):",
      gpu_smoke_test(Path("/tmp/hfai-smoke"), device="cuda" if GPUS else "cpu"))"""),
    ("markdown", "## 3. Check the data sources against what our code expects"),
    ("code", """from hfai.kaggle import verify_sources
if DRY_RUN:
    print("Dry run: skipping the Hugging Face sources.")
else:
    checks = verify_sources()
    for c in checks:
        print(("OK     " if c["ok"] else "FAILED ") + f"{c['source']} {c['config'] or ''}: fields {c['fields']}")
        if c["licence_labels"]:
            print("        licence labels seen:", c["licence_labels"])
        if c["problem"]:
            print("        problem:", c["problem"])
    if not all(c["ok"] for c in checks):
        raise SystemExit("A data source is not what our code expects. Please paste the lines above into the chat.")
    print("All sources match. Documents with licence labels marked NOT RECOGNISED will be dropped and counted.")"""),
    ("markdown", "## 4. The plan, then download and clean the text"),
    ("code", """import json
from pathlib import Path
from hfai.kaggle import RunPlan, download_mix
plan = RunPlan(dry_run=DRY_RUN)
if DRY_RUN:
    plan = RunPlan(dry_run=True, vocab_size=2048, preset="tiny", batch_size=8, grad_accum=1, max_steps=60,
                   max_train_minutes=5, lr=1e-3, tokenizer_sample_mb_per_language=1, tokenizer_english_sample_mb=3)
print(plan.describe())
RAW, CACHE = Path("/tmp/hfai-raw"), Path("/tmp/hfai-cache")
stats = download_mix(plan, RAW, CACHE)
Path(WORK, "download-stats.json").write_text(json.dumps(stats, indent=2))
for key, value in sorted(stats.items()):
    print(f"{key}: {value}")"""),
    ("markdown", "## 5. Train our multilingual tokenizer and measure language coverage"),
    ("code", """from hfai.kaggle import train_tokenizer, run
TOKENIZER = Path(WORK, "tokenizer.json")
train_tokenizer(plan, RAW, TOKENIZER)
COVERAGE = Path(WORK, "tokenizer-coverage.md")
run([sys.executable, "-m", "hfai.tokenizer", "report", str(TOKENIZER), "--out", str(COVERAGE), "--title", "Kaggle tokenizer"])
print(COVERAGE.read_text()[:3000])"""),
    ("markdown", "## 6. Turn the text into training data"),
    ("code", """from hfai.kaggle import build_shards
DATA = Path("/tmp/hfai-shards")
report = build_shards(RAW, TOKENIZER, DATA)
print(json.dumps(report["totals"], indent=2))"""),
    ("markdown", "## 7. Train the model (this is the long step; it stops itself before the time budget)"),
    ("code", """from hfai.kaggle import train_command
RUN = Path(WORK, "run")
run(train_command(plan, DATA, TOKENIZER, RUN, GPUS))"""),
    ("markdown", "## 8. The report card"),
    ("code", """run([sys.executable, "-m", "hfai.training", "report", "--run", str(RUN), "--tokenizer", str(TOKENIZER),
     "--data", str(DATA), "--title", "Kaggle training run"])
from IPython.display import Markdown, SVG, display
display(Markdown(Path(RUN, "report.md").read_text()))
display(SVG(filename=str(Path(RUN, "loss.svg"))))"""),
    ("markdown", "## 9. Collect the results"),
    ("code", """from hfai.kaggle import collect_outputs
copied = collect_outputs(RUN, TOKENIZER, COVERAGE, DATA, Path(WORK, "outputs"))
print("Saved in outputs/:", copied)
print("Done. Download outputs/report.md from the Output tab and paste it into the chat.")"""),
]


def build() -> dict:
    cells = []
    for kind, source in CELLS:
        cell = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
        if kind == "code":
            cell.update({"execution_count": None, "outputs": []})
        cells.append(cell)
    return {
        "cells": cells,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


if __name__ == "__main__":
    path = Path(__file__).with_name("kaggle_train.ipynb")
    path.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path}")
