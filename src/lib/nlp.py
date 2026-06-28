import contextlib
import json
import os
import pickle
import re
import sqlite3
import subprocess
import sys
import warnings
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast, Literal, TypedDict

# Suppress deprecation warning from thinc about torch.cuda.amp.autocast
warnings.filterwarnings("ignore", message=r".*torch\.cuda\.amp\.autocast.*", category=FutureWarning)
warnings.filterwarnings("ignore", message=r".*torch\.amp\.autocast.*", category=FutureWarning)
warnings.filterwarnings("ignore", category=FutureWarning, module=r"thinc\..*")

import nltk
import spacy
from nltk.corpus import webtext, words
from spacy.language import Language
from spacy.matcher import Matcher

from lib.misc import re_group
from src.lib.config import cfg
from src.lib.term import print_debug

SPACY_MODEL_TRF = "en_core_web_trf"
SPACY_MODEL_SM = "en_core_web_sm"
TRF_MODEL = "dslim/bert-base-NER"


def should_update_nltk() -> bool:
    nltk_file = cfg.META_DIR / ".nltk"
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
webtext_words = set()


def update_nltk_timestamp():
    nltk_file = cfg.META_DIR / ".nltk"
    with open(nltk_file, "w") as f:
        json.dump({"last_update": datetime.now().isoformat()}, f)


if should_update_nltk():
    with contextlib.redirect_stdout(open(os.devnull, "w")):
        nltk.download("words")
        nltk.download("webtext")
        english_words = set(words.words())
        webtext_words = set(webtext.words())
    update_nltk_timestamp()
else:
    english_words = set(words.words())
    webtext_words = set(webtext.words())

nlp = None  # type: ignore


def _ensure_pip():
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print_debug("pip not found in venv, bootstrapping via ensurepip...")
        result = subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True)
        if result.returncode != 0:
            print_debug(f"ensurepip failed: {result.stderr.decode().strip()}")


@contextlib.contextmanager
def _devnull():
    with open(os.devnull, "w") as null:
        with contextlib.redirect_stdout(null), contextlib.redirect_stderr(null):
            yield


def _load_spacy_model() -> spacy.language.Language:
    # en_core_web_trf requires spacy-curated-transformers which is only
    # installed on macOS (Apple Silicon). Skip it on other platforms.
    models = (SPACY_MODEL_TRF, SPACY_MODEL_SM) if sys.platform == "darwin" else (SPACY_MODEL_SM,)
    for model in models:
        try:
            with _devnull():
                return spacy.load(model)
        except (OSError, ValueError):
            print_debug(f"spaCy model '{model}' not found or missing plugin, trying to download...")
            _ensure_pip()
            result = subprocess.run([sys.executable, "-m", "spacy", "download", model], capture_output=True)
            if result.returncode == 0:
                try:
                    return spacy.load(model)
                except (OSError, ValueError) as e:
                    print_debug(f"Failed to load '{model}' after download: {e}")
            else:
                print_debug(f"Failed to download '{model}': {result.stderr.decode().strip()}")
    raise RuntimeError(f"Could not load any spaCy model (tried: {', '.join(models)})")


nlp = _load_spacy_model()


matcher = Matcher(nlp.vocab)
matcher.add("PERSON", [[{"IS_ALPHA": True}]])
matcher.add("WORK_OF_ART", [[{"IS_ALPHA": True}]])
matcher.add("PRODUCT", [[{"IS_ALPHA": True}]])
matcher.add("EVENT", [[{"IS_ALPHA": True}]])
matcher.add("ORG", [[{"IS_ALPHA": True}]])

import inflect as _inflect

inflect = _inflect.engine()
nlp = cast(Language, nlp)

"""
[{'entity_group': 'PER', 'score': 0.9915958, 'word': 'Melody Muze', 'start': 0, 'end': 11}, {'entity_group': 'PER', 'score': 0.9990646, 'word': 'Fe', 'start': 15, 'end': 17}, {'entity_group': 'PER', 'score': 0.68379545, 'word': '##yre', 'start': 17, 'end': 20}]
special variables
function variables
0 = {'entity_group': 'PER', 'score': 0.9915958, 'word': 'Melody Muze', 'start': 0, 'end': 11}
1 = {'entity_group': 'PER', 'score': 0.9990646, 'word': 'Fe', 'start': 15, 'end': 17}
2 = {'entity_group': 'PER', 'score': 0.68379545, 'word': '##yre', 'start': 17, 'end': 20}
"""
DslimBertBaseNER = TypedDict(
    "DslimBertBaseNER",
    {
        "entity_group": Literal["PER", "ORG", "PRODUCT", "EVENT", "WORK_OF_ART", "GPE", "LAW"],
        "score": float,
        "word": str,
        "start": int,
        "end": int,
    },
)


def get_model_cache_db() -> sqlite3.Connection:
    """Get or create the SQLite database connection for model caching."""
    db_path = cfg.META_DIR / "model_cache.db"
    conn = sqlite3.connect(str(db_path))

    # Check if we need to migrate from old schema
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT results FROM model_cache LIMIT 1")
    except sqlite3.OperationalError:
        # Old schema exists, migrate to new schema
        cursor.execute("DROP TABLE IF EXISTS model_cache")
        cursor.execute(
            """
            CREATE TABLE model_cache (
                model_name TEXT,
                input_text TEXT,
                results BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (model_name, input_text)
            )
        """
        )
        conn.commit()
    else:
        # Table exists with new schema, ensure it has all columns
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS model_cache (
                model_name TEXT,
                input_text TEXT,
                results BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (model_name, input_text)
            )
        """
        )

    return conn


def get_transformer_pipeline(pipeline, *, model_name: str) -> Callable[[str], list[DslimBertBaseNER]]:
    """Get a transformer pipeline for NER with result caching.

    Args:
        model_name: The name of the model to use

    Returns:
        A callable that takes a string and returns a list of NER results
    """
    # Create the pipeline
    tokenizer = AutoTokenizer.from_pretrained(model_name, never_split=[])
    model = AutoModelForTokenClassification.from_pretrained(model_name)
    pipeline = cast(
        Callable[[str], list[DslimBertBaseNER]],
        pipeline("ner", model=model, tokenizer=tokenizer, aggregation_strategy="simple"),
    )

    # Create a wrapper that caches results
    def cached_pipeline(text: str) -> list[DslimBertBaseNER]:
        conn = get_model_cache_db()
        cursor = conn.cursor()

        # Try to get from cache
        cursor.execute("SELECT results FROM model_cache WHERE model_name = ? AND input_text = ?", (model_name, text))
        result = cursor.fetchone()

        if result is not None:
            try:
                cached_results = pickle.loads(result[0])
                conn.close()
                return cached_results
            except (pickle.UnpicklingError, EOFError):
                # If unpickling fails, we'll recompute the results
                pass

        # Compute new results
        results = pipeline(text)

        # Cache the results
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO model_cache (model_name, input_text, results) VALUES (?, ?, ?)",
                (model_name, text, pickle.dumps(results)),
            )
            conn.commit()
        except Exception as e:
            print_debug(f"Failed to cache NER results: {e}")

        conn.close()
        return results

    return cached_pipeline


class NoTRF:
    def __init__(self): ...

    def __call__(self, s: str):
        return cast(list[DslimBertBaseNER], [])


try:
    from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

    with _devnull(), warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        nlp_trf = get_transformer_pipeline(pipeline, model_name=TRF_MODEL)
except Exception as e:
    print_debug(f"Error loading transformer model: {e}")
    nlp_trf = NoTRF()


def squash_trf_results(results: list[DslimBertBaseNER]) -> list[DslimBertBaseNER]:
    """Combines results from the transformer that have been split, and have adjacent char positions. E.g., given:

    0 = {'entity_group': 'PER', 'score': 0.9915958, 'word': 'Melody Muze', 'start': 0, 'end': 11}
    1 = {'entity_group': 'PER', 'score': 0.9990646, 'word': 'Fe', 'start': 15, 'end': 17}
    2 = {'entity_group': 'PER', 'score': 0.68379545, 'word': '##yre', 'start': 17, 'end': 20}

    Because 1 and 2 are character-adjacent, we combine them into a single result and average the scores:

    0 = {'entity_group': 'PER', 'score': 0.9915958, 'word': 'Melody Muze', 'start': 0, 'end': 11}
    1 = {'entity_group': 'PER', 'score': 0.84143, 'word': 'Feyre', 'start': 15, 'end': 20}

    Returns:
    """
    results = sorted(results, key=lambda x: x["start"])
    combined = []
    for i, result in enumerate(results):
        if i == 0:
            combined.append(result)
        else:
            if result["start"] == results[i - 1]["end"]:
                prev = combined[-1]["score"]
                curr = result["score"]
                max_sig_digs = max(len(str(prev).split(".")[1]), len(str(curr).split(".")[1]))
                combined[-1]["score"] = round((prev + curr) / 2, max_sig_digs)

                # Handle character-by-character alignment
                prev_word = combined[-1]["word"]
                next_word = result["word"]
                aligned_word = ""

                # Process each character in the next word
                for j, char in enumerate(next_word):
                    if char == "#":
                        # Find the corresponding character in the previous word
                        # based on the position difference
                        pos_diff = result["start"] - combined[-1]["start"]
                        if j + pos_diff < len(prev_word):
                            aligned_word += prev_word[j + pos_diff]
                    else:
                        aligned_word += char

                combined[-1]["word"] = f"{prev_word}{aligned_word}"
            else:
                combined.append(result)
    return combined


def squash_nlp_results(
    results: list[tuple[str, str, float] | tuple[str, str, None]],
) -> list[tuple[str, str, float]]:
    """Combines results from the multiple nlp result sets in the (name, label, score) format.
    If duplicate names are found, keep the one with the lowest score if the difference is less than 0.1, otherwise average the scores.

    Args:
        results: A list of tuples containing the name, label, and score of the results

    Returns:
        A list of tuples containing the combined name, label, and score of the results
    """
    # Group results by name
    name_groups: dict[str, list[tuple[str, str, float | None]]] = {}
    for result in results:
        name = result[0]

        # Check if this name is a substring of any existing key
        found_match = False
        for existing_name in list(name_groups.keys()):
            if name in existing_name:
                # If current name is a substring, add to existing group
                name_groups[existing_name].append(result)
                found_match = True
                break
            elif existing_name in name:
                # If existing name is a substring, move all entries to new key
                name_groups[name] = name_groups.pop(existing_name)
                name_groups[name].append(result)
                found_match = True
                break

        # If no matches found, create new group
        if not found_match:
            name_groups[name] = []
            name_groups[name].append(result)

    # Process each group
    combined_results: list[tuple[str, str, float | None]] = []
    for name, group in name_groups.items():
        if len(group) == 1:
            # No duplicates, keep as is
            combined_results.append(group[0])
        else:
            # Handle duplicates
            scores = [s for _, _, s in group if s is not None]
            min_score = min(scores)
            max_score = max(scores)

            no_nones = cast(list[tuple[str, str, float]], [g for g in group if g[2] is not None])
            if len(no_nones) == 0:
                continue

            if max_score - min_score < 0.1:
                # Keep the one with lowest score
                lowest_score_entry = min(no_nones, key=lambda x: x[2])
                combined_results.append(lowest_score_entry)
            else:
                # Average the scores
                avg_score = sum(scores) / len(scores)
                # Use the label from the entry with highest score
                highest_score_entry = max(no_nones, key=lambda x: x[2])
                combined_results.append((name, highest_score_entry[1], avg_score))

    return cast(list[tuple[str, str, float]], sorted(combined_results, key=lambda x: x[2] or 0, reverse=True))


def get_nlp_cache_db() -> sqlite3.Connection:
    """Get or create the SQLite database connection for NLP caching."""
    db_path = cfg.META_DIR / "nlp_cache.db"
    conn = sqlite3.connect(str(db_path))

    # Create table if it doesn't exist
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nlp_cache (
            input_text TEXT,
            results BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (input_text)
        )
    """
    )
    return conn


def get_cached_nlp_results(text: str) -> list[tuple[str, str, float]] | None:
    """Get cached NLP results for the given text."""
    conn = get_nlp_cache_db()
    cursor = conn.cursor()

    cursor.execute("SELECT results FROM nlp_cache WHERE input_text = ?", (text,))
    result = cursor.fetchone()
    conn.close()

    if result is not None:
        try:
            return pickle.loads(result[0])
        except (pickle.UnpicklingError, EOFError):
            return None
    return None


def cache_nlp_results(text: str, results: list[tuple[str, str, float]]) -> None:
    """Cache NLP results for the given text."""
    conn = get_nlp_cache_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT OR REPLACE INTO nlp_cache (input_text, results) VALUES (?, ?)",
            (text, pickle.dumps(results)),
        )
        conn.commit()
    except Exception as e:
        print_debug(f"Failed to cache NLP results: {e}")
    finally:
        conn.close()


def restore_original_name(s: str, results: list[tuple[str, str, float]]) -> list[tuple[str, str, float]]:
    """Restore the original name from the results by looking for each result as a substring
    in s, and if found, restoring any letter characters on either side that are not separated
    by non-word chars.

    E.g., if the string is "Melody Muze as Feyre", and the results are [("Melody Muz", "PER", 1.0), ("Fey", "PER", 1.0)],
    we restore "Melody Muze" to "Melody Muze" and "Feyre" to "Feyre".
    """
    restored: list[tuple[str, str, float]] = []
    for name, label, score in results:
        if label.startswith("PER") or label == "AUTHOR":
            # Find the first occurrence of the name in s
            start = s.find(name)
            if start != -1:
                # Create a regex pattern to match the name and any word chars on either side
                pattern = re.compile(r"(?:^|(?<=\W))(?P<name>\S*{name}\S*)(?=\W|$)".format(name=re.escape(name)))
                restored_name = re_group(pattern.search(s), "name", default=name)
                restored.append((restored_name, label, score))
            else:
                restored.append((name, label, score))
        else:
            restored.append((name, label, score))
    return restored
