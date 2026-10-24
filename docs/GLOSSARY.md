# Glossary: plain-language explanations

Terms are added here the first time the project uses them. If something is unclear, please open an issue. That's a bug in this page.

## AI and machine learning

**Model.** A very large set of numbers plus the fixed recipe (code) that uses them to turn input into output. Our model reads text and predicts what text comes next.

**Parameters / weights.** The numbers inside the model. "25M parameters" means 25 million numbers. Training adjusts them; once trained, they *are* what the model has learned. A file of weights is like the model's memory, frozen.

**Training.** Showing the model a huge amount of text, one small piece at a time. For each piece the model guesses the next word, checks the real answer, and nudges its weights slightly so that next time it guesses a little better. Repeat billions of times. This is pure arithmetic, and it needs a lot of computing power.

**Token.** A small piece of text, often a word or part of a word ("un", "believ", "able"). Models read and write tokens, not letters or whole words.

**Tokenizer.** The tool that splits text into tokens and joins tokens back into text. We build our own.

**BPE (byte-pair encoding).** A simple way to build a tokenizer. Start from single bytes (the basic units computers use to store any character in any language), then repeatedly merge the most common neighbouring pair into a new token. Because it starts from bytes, it can handle every writing system.

**Loss.** A score for how wrong the model's guesses are. Training tries to push it down. A **falling loss curve** is the main sign that a model is learning.

**Transformer.** The design of model we use, published by researchers in 2017 and now standard. It reads a sequence of tokens and uses **attention** (each token "looking at" earlier tokens to decide what matters) to predict the next one. Using this published design is like using a known recipe; our code and weights are our own.

**Inference.** Using a trained model to produce output, as opposed to training it. Much cheaper than training: a small model can run on an ordinary laptop.

**Checkpoint.** A saved snapshot of the model's weights (and training progress) part-way through training, so training can resume after a stop. Important on Kaggle, where sessions end after about 9–12 hours.

**Evaluation.** Measuring how well a model does, on text it has never seen, or on tests designed for a specific behaviour.

**Fine-tuning / instruction tuning.** Extra training of an already-trained model on a smaller, focused dataset, for example human-written conversations, so it learns to respond to requests. We only ever fine-tune *our own* model.

**Retrieval / BM25.** Searching a library for passages relevant to a question. BM25 is a classic formula from the 1990s that ranks passages by how many of the question's words they contain, weighted by how rare those words are. It is not an AI, and it never makes things up.

**Hallucination.** When a model writes something that sounds confident but is false. Small models do this a lot. That is why our assistant shows sources.

## Hardware and cost

**GPU (graphics processing unit).** A chip originally built for video games that does huge numbers of simple sums at once, which is exactly what training needs. Kaggle lends free GPUs (two NVIDIA T4s).

**CPU.** A computer's general-purpose processor. It can train tiny models, slowly.

**fp16 ("half precision").** Storing numbers with less detail (16 bits instead of 32) so training is faster and uses less memory. The T4 GPU is fast at fp16.

**kWh (kilowatt-hour).** A unit of energy: running a 1,000-watt heater for one hour uses 1 kWh. We report the estimated energy of every training run.

## Safety and security

**Consent gate.** The part of the safety layer that stops any action until a human clicks "allow" for that specific action.

**Kill switch.** A control that immediately and forcibly stops the AI's process on your device. It works without the AI's cooperation.

**Hash / fingerprint (SHA-256).** A short code calculated from a file's contents. Change even one letter of the file and the fingerprint changes completely. Used to detect tampering.

**Hash chain.** A log where each entry includes the fingerprint of the entry before it. Editing any old entry breaks every fingerprint after it, so tampering is visible ("tamper-evident").

**Digital signature.** A way for a person holding a secret key to "sign" a file so that anyone can check, using a public key, that the file is exactly what that person signed.

**Policy language / Charter Rules.** A tiny language of our own, used only to write the rules for what actions the AI may propose. It is deliberately limited (no loops, no file or internet access) so the rules are easy to check and cannot do anything harmful themselves.

**Prompt injection.** An attack where text the AI reads (a web page, a document) contains hidden instructions, hoping the AI will obey them. Our defence: text the AI reads is treated as information, never as commands, and every action still needs your consent.

**Data poisoning.** Deliberately adding bad text to training data so the model learns something harmful.

## Decentralisation

**Peer-to-peer (P2P).** Computers sharing directly with each other, with no central server in charge.

**Sybil attack.** One attacker pretending to be many independent participants (many fake "peers") to gain outsized influence.

**DiLoCo.** A published method for training one model across many computers with slow internet connections. Each computer trains on its own for a while, then they share and average their changes.

**Robust aggregation.** Combining updates from many peers in a way that a few bad or malicious updates cannot pull the result far off, for example by taking the median instead of the average.
