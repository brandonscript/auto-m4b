FROM auto-m4b-base:latest

COPY src/ ./src/

ENV PYTHONPATH=.
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
