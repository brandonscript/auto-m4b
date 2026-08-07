# syntax=docker/dockerfile:1
# Requires BuildKit additional_contexts (see docker-compose.template.yml):
#   goodscraps → sibling checkout, bookpeek → sibling checkout
# ── Stage 1: base (system deps + Python packages + NLP models) ───────────────
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

WORKDIR /app

# Path deps in pyproject.toml are ../goodscraps and ../bookpeek relative to /app
COPY --from=goodscraps . /goodscraps/
COPY --from=bookpeek . /bookpeek/

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

# Download NLP models at build time
RUN python -m spacy download en_core_web_sm
RUN python -c "import nltk; [nltk.download(p, quiet=True) for p in \
    ('popular', 'punkt_tab', 'averaged_perceptron_tagger_eng', \
     'maxent_ne_chunker_tab', 'words', 'stopwords')]"

# Pre-create the ~/.auto-m4b dir and stamp the NLTK timestamp so that nlp.py
# does not re-download NLTK corpora on every fresh container start.
RUN python -c "\
import json, os, pathlib; \
from datetime import datetime; \
d = pathlib.Path.home() / '.auto-m4b'; \
d.mkdir(parents=True, exist_ok=True); \
(d / '.nltk').write_text(json.dumps({'last_update': datetime.now().isoformat()}))"

# ── Stage 2: app ──────────────────────────────────────────────────────────────
FROM base

COPY src/ ./src/

ENV PYTHONPATH=.
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
