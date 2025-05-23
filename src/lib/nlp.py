import contextlib
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import nltk
import spacy
from nltk.corpus import words
from spacy.language import Language
from spacy.matcher import Matcher

from src.lib.term import print_debug

META_DIR = Path.home() / ".auto-m4b"
META_DIR.mkdir(parents=True, exist_ok=True)


def should_update_nltk() -> bool:
    nltk_file = META_DIR / ".nltk"
    if not nltk_file.exists():
        return True

    try:
        with open(nltk_file, "r") as f:
            data = json.load(f)
            last_update = datetime.fromisoformat(data["last_update"])
            return datetime.now() - last_update > timedelta(days=30)
    except (json.JSONDecodeError, KeyError, ValueError):
        return True


english_words = set()


def update_nltk_timestamp():
    nltk_file = META_DIR / ".nltk"
    with open(nltk_file, "w") as f:
        json.dump({"last_update": datetime.now().isoformat()}, f)


if should_update_nltk():
    with contextlib.redirect_stdout(open(os.devnull, "w")):
        nltk.download("words")
        english_words = set(words.words())
    update_nltk_timestamp()
else:
    english_words = set(words.words())

nlp = None  # type: ignore

try:
    # Load spaCy model silently by redirecting stdout/stderr temporarily
    with contextlib.redirect_stdout(open(os.devnull, "w")), contextlib.redirect_stderr(open(os.devnull, "w")):
        nlp = spacy.load("en_core_web_sm")
except Exception as e:
    print_debug(f"Error loading spaCy model: {e}")
    # run `python -m spacy download en`
    subprocess.run(["python", "-m", "spacy", "download", "en_core_web_sm"])
    nlp = spacy.load("en_core_web_sm")


matcher = Matcher(nlp.vocab)
matcher.add("PERSON", [[{"IS_ALPHA": True}]])
matcher.add("WORK_OF_ART", [[{"IS_ALPHA": True}]])
matcher.add("PRODUCT", [[{"IS_ALPHA": True}]])
matcher.add("EVENT", [[{"IS_ALPHA": True}]])
matcher.add("ORG", [[{"IS_ALPHA": True}]])

import inflect as _inflect

inflect = _inflect.engine()
nlp = cast(Language, nlp)
