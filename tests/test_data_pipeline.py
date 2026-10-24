"""The data pipeline must enforce the data rules and report everything it drops."""

import json
import zipfile
from array import array

import pytest

from hfai.data.filters import Cleaner, scrub_personal_info
from hfai.data.pipeline import build, is_validation
from hfai.data.sources import (
    Document,
    check_allowed,
    fetch_gutenberg,
    iter_cldr,
    normalise_licence,
)
from hfai.tokenizer import train

ALLOWED = {"public-domain", "CC-BY-4.0"}


def doc(text="A perfectly ordinary paragraph of human writing.", licence="public-domain", doc_id="1", source="test"):
    return Document(source, doc_id, text, licence, "en")


def test_licence_must_be_allowed():
    kept, reason = Cleaner(ALLOWED).clean(doc(licence="CC-BY-NC-4.0"))
    assert kept is None and "licence not allowed" in reason


def test_ai_written_text_dropped():
    kept, reason = Cleaner(ALLOWED).clean(doc("Sure. As an AI language model, I cannot have opinions on this."))
    assert kept is None and "AI-written" in reason


def test_short_and_duplicate_dropped():
    cleaner = Cleaner(ALLOWED)
    assert cleaner.clean(doc("too short"))[1] == "too short"
    assert cleaner.clean(doc())[1] == "kept"
    assert cleaner.clean(doc(doc_id="2"))[1] == "exact duplicate"


def test_personal_info_scrubbed():
    text, count = scrub_personal_info("Write to jane.doe@example.org or call +64 21 123 4567 before 1999.")
    assert "jane.doe" not in text and "123 4567" not in text and count == 2
    assert "1999" in text  # ordinary numbers stay


def test_text_is_normalised():
    kept, _ = Cleaner(ALLOWED).clean(doc("Café au lait\r\nis a drink that people like."))
    assert "Café" in kept.text and "\r" not in kept.text


@pytest.mark.parametrize("source_id", ["tinystories", "alpaca", "fineweb", "the-pile", "udhr-translations"])
def test_excluded_sources_refused(source_id):
    with pytest.raises(ValueError, match="excluded"):
        check_allowed(source_id)


def test_unlisted_source_refused():
    with pytest.raises(ValueError, match="not listed"):
        check_allowed("random-web-scrape")


def test_unrecognised_licence_labels_are_not_guessed():
    assert normalise_licence("CC-By-SA") == "CC-BY-SA-4.0"
    assert normalise_licence("All rights reserved") is None
    assert normalise_licence("CC-BY-NC") is None


def test_gutenberg_archive_must_match_its_fingerprint(tmp_path):
    folder = tmp_path / "nltk-gutenberg"
    folder.mkdir()
    with zipfile.ZipFile(folder / "gutenberg.zip", "w") as zf:
        zf.writestr("gutenberg/austen-emma.txt", "tampered")
    with pytest.raises(ValueError, match="does not match"):
        fetch_gutenberg(tmp_path)


def test_cldr_has_hundreds_of_languages_and_held_out_parts():
    pytest.importorskip("babel")
    train_docs = {d.doc_id: d for d in iter_cldr(part="train")}
    eval_docs = {d.doc_id: d for d in iter_cldr(part="eval")}
    assert len(train_docs) > 200 and len(eval_docs) > 200
    assert all(d.licence == "Unicode-3.0" for d in train_docs.values())
    assert set(train_docs["mi"].text.splitlines()).isdisjoint(eval_docs["mi"].text.splitlines())


def test_build_writes_shards_and_a_full_report(tmp_path):
    texts = [f"Document number {i} talks about gardens, rivers and kindness." for i in range(200)]
    tokenizer = train(texts, 400)
    docs = [doc(t, doc_id=str(i)) for i, t in enumerate(texts)]
    docs.append(doc("As an AI language model I must refuse to write this paragraph.", doc_id="ai"))
    docs.append(doc("Some text under a licence that is not allowed here at all.", licence="CC-BY-NC-4.0", doc_id="nc"))
    report = build(docs, tokenizer, tmp_path / "out", val_fraction=0.1, cleaner=Cleaner(ALLOWED))

    info = report["sources"]["test"]
    assert info["kept_and_dropped"]["kept"] == 200
    assert sum(v for k, v in info["kept_and_dropped"].items() if k != "kept") == 2
    for split in ("train", "val"):
        ids = array("H")
        ids.frombytes((tmp_path / "out" / f"{split}.bin").read_bytes())
        assert len(ids) == info[f"{split}_tokens"]
        assert ids[-1] == tokenizer.token_id("<|endoftext|>")
    assert 0 < info["val_documents"] < 60
    saved = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert saved["tokenizer_fingerprint"] == tokenizer.fingerprint


def test_validation_split_is_stable():
    d = doc(doc_id="stable")
    assert is_validation(d, 0.5) == is_validation(d, 0.5)
