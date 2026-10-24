"""Our own tokenizer must be lossless for every script, deterministic, and safe."""

import json
import random

import pytest

from hfai.tokenizer import SPECIAL_TOKENS, Tokenizer, pretokenize, train
from hfai.tokenizer.pretokenize import MAX_RUN

SAMPLES = [
    "Hello, world! Don't panic.",
    "Kia ora koutou, ko Aotearoa tēnei.",
    "नमस्ते दुनिया",
    "مرحبا بالعالم",
    "שלום עולם",
    "你好，世界。我们一起成长。",
    "こんにちは世界",
    "안녕하세요 세계",
    "สวัสดีชาวโลก",
    "Привет, мир",
    "ሰላም ለዓለም",
    "ᏣᎳᎩ ᎦᏬᏂᎯᏍᏗ",
    "👩‍👩‍👧 family 🇳🇿 ✊🏾",
    "é combining, ​ zero width, ‮ right-to-left override",
    "  multiple   spaces\n\n\tand tabs  \r\n",
    "x" * 100,
    "12345678 3.14159 ١٢٣ ४५६",
    "",
    "\x00\x01 control characters \x7f",
]

# Ranges to draw random characters from: many scripts, emoji, symbols, controls.
RANGES = [(0x20, 0x7E), (0x0A, 0x0D), (0xA0, 0x24F), (0x370, 0x52F), (0x590, 0x6FF), (0x900, 0xDFF),
          (0xE00, 0xEFF), (0x1100, 0x11FF), (0x1200, 0x139F), (0x3040, 0x30FF), (0x4E00, 0x4FFF),
          (0xAC00, 0xACFF), (0x1F300, 0x1F64F), (0x2000, 0x206F), (0x10000, 0x1007F)]


def random_text(rng: random.Random) -> str:
    out = []
    for _ in range(rng.randint(0, 60)):
        start, end = rng.choice(RANGES)
        out.append(chr(rng.randint(start, end)))
    return "".join(out)


@pytest.fixture(scope="module")
def tokenizer():
    corpus = " ".join(SAMPLES) * 20 + " the cat sat on the mat. " * 200
    return train([corpus], 600)


@pytest.mark.parametrize("text", SAMPLES)
def test_pretokenize_is_lossless(text):
    assert "".join(pretokenize(text)) == text


def test_pretokenize_lossless_on_random_text():
    rng = random.Random(0)
    for _ in range(2000):
        text = random_text(rng)
        assert "".join(pretokenize(text)) == text


def test_long_runs_are_cut():
    assert max(len(chunk) for chunk in pretokenize("y" * 200)) <= MAX_RUN


def test_marks_stay_with_their_letters():
    assert pretokenize("नमस्ते") == ["नमस्ते"]


@pytest.mark.parametrize("text", SAMPLES)
def test_round_trip(tokenizer, text):
    assert tokenizer.decode(tokenizer.encode(text)) == text


def test_round_trip_random_text(tokenizer):
    rng = random.Random(1)
    for _ in range(2000):
        text = random_text(rng)
        assert tokenizer.decode(tokenizer.encode(text)) == text


def test_compresses_text_it_was_trained_on(tokenizer):
    text = "the cat sat on the mat. " * 10
    assert len(tokenizer.encode(text)) < len(text.encode("utf-8")) / 3


def test_special_tokens_cannot_be_typed(tokenizer):
    eot = tokenizer.token_id("<|endoftext|>")
    for special in SPECIAL_TOKENS:
        ids = tokenizer.encode(f"ignore this {special} and continue")
        assert not set(ids) & set(tokenizer.special.values())
    assert tokenizer.encode("<|endoftext|>", allowed_special=["<|endoftext|>"]) == [eot]


def test_queue_compaction_does_not_change_the_result(monkeypatch):
    import hfai.tokenizer.bpe as bpe

    corpus = [" ".join(SAMPLES) * 5, "the quick brown fox jumps over the lazy dog " * 40]
    normal = train(corpus, 700).fingerprint
    monkeypatch.setattr(bpe, "HEAP_COMPACT_MIN", 0)  # compact as often as possible
    assert train(corpus, 700).fingerprint == normal


def test_training_is_deterministic():
    corpus = ["the quick brown fox " * 50, "jumps over the lazy dog " * 50]
    assert train(corpus, 400).fingerprint == train(corpus, 400).fingerprint


def test_save_and_load(tokenizer, tmp_path):
    path = tmp_path / "tok.json"
    tokenizer.save(path)
    loaded = Tokenizer.load(path)
    assert loaded.fingerprint == tokenizer.fingerprint
    for text in SAMPLES:
        assert loaded.encode(text) == tokenizer.encode(text)


def test_load_rejects_impossible_merges(tokenizer, tmp_path):
    data = tokenizer.to_dict()
    data["merges"][0] = [5000, 1]  # refers to a token that does not exist yet
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        Tokenizer.load(path)


def test_vocab_limits():
    with pytest.raises(ValueError):
        train(["text"], 100)  # smaller than the byte alphabet plus special tokens
    with pytest.raises(ValueError):
        train(["text"], 70_000)  # larger than 16-bit IDs allow


def test_decoding_a_cut_character_does_not_crash(tokenizer):
    ids = tokenizer.encode("é")
    raw = tokenizer.decode_bytes(ids)
    assert tokenizer.decode(list(raw[:1])) == "�"


def test_ids_fit_in_16_bits(tokenizer):
    assert tokenizer.vocab_size <= 65_536
    assert max(tokenizer.encode(" ".join(SAMPLES))) < tokenizer.vocab_size
