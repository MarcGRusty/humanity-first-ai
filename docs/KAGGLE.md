# Running the training on Kaggle: step by step

This is how the real training run happens, on Kaggle's free GPUs. You do not need to write any code. Allow about **15 minutes of your time** the first time, then the notebook runs by itself for **about 8–10 hours**.

## What Kaggle is, and why we use it

Kaggle (owned by Google) lends free GPUs, about **30 GPU-hours a week**, to anyone with a verified account. Training needs a GPU, and this is the cheapest honest option: it costs you nothing, and the only things that go to Kaggle are our open code and public training data. None of your personal data goes there.

It is a temporary bootstrap. Depending on a company does not fit the long-term goal of no single point of control, so Phase 2 replaces it with volunteer computers (see [ROADMAP.md](../ROADMAP.md)).

## One-time setup (about 10 minutes)

1. Go to https://www.kaggle.com and **register** (free).
2. **Verify your phone number**: click your profile picture → **Settings** → **Phone verification**. Kaggle requires this before it allows GPUs and internet access in notebooks.

## Each training run

1. Download the notebook file from the project: [`notebooks/kaggle_train.ipynb`](../notebooks/kaggle_train.ipynb). On GitHub, open the file and click the **download** button ("Download raw file").
2. On Kaggle: **Create → New Notebook**. In the notebook, use **File → Import Notebook** and choose the file you downloaded.
3. In the right-hand panel, under **Session options**:
   - **Accelerator: GPU T4 x2.** Not the P100: newer PyTorch no longer supports it, and the notebook will refuse it.
   - **Internet: On.**
4. Click **Save Version** (top right) → choose **Save & Run All (Commit)** → **Save**.
5. That's it. It runs in the background, even if you close the browser. Kaggle emails you, or shows the version as complete, when it is done.

## When it finishes

1. Open the notebook → **Versions** → the latest version → **Output**.
2. Download `outputs/report.md`, and if you like the rest of `outputs/`: the trained model `model.pt`, the tokenizer, the coverage report and the loss chart.
3. **Paste the contents of `report.md` into our chat.** I'll check it against the estimates in [MODEL_OPTIONS.md](MODEL_OPTIONS.md) and record the real numbers.

## If something goes wrong

Every step prints what it is doing. If a step fails, copy the last 20 or so lines of output into the chat. The most likely failures are:

| Message | What it means | What to do |
|---|---|---|
| "No GPU found" or "too old for current PyTorch" | Wrong accelerator | Session options → Accelerator: **GPU T4 x2**, then Save & Run All again |
| "Could not get the code from GitHub" | Internet is off | Session options → **Internet: On** (needs phone verification) |
| "A data source is not what our code expects" | A dataset changed, or my untested guess about it was wrong | Paste the printed table into the chat; I fix the adapter |
| The run stops at about 12 hours | Kaggle's session limit | The notebook budgets 7 hours for training to stay well inside it; tell me and I'll shrink the plan |

## What it costs

- **Your time:** about 15 minutes for the first setup, then 2 minutes per run.
- **GPU time:** about 7–8 of your 30 free weekly hours.
- **Energy:** roughly 1–2 kWh of Kaggle's electricity. The report gives the measured GPU figure; the host computer adds more.
- **Money:** none.
