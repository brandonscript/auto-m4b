FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main

# Download NLP models at build time
RUN python -m spacy download en_core_web_sm
RUN python -c "import nltk; [nltk.download(p, quiet=True) for p in \
    ('punkt_tab', 'averaged_perceptron_tagger_eng', \
     'maxent_ne_chunker_tab', 'words', 'stopwords')]"

COPY src/ ./src/

ENV PYTHONPATH=.
CMD ["python", "-m", "src"]
