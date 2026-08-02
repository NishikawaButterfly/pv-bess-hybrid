FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md requirements.txt requirements-api.txt ./
COPY src ./src
COPY web ./web
COPY sample-data ./sample-data

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt -r requirements-api.txt \
    && python -m pip install .

ENV PV_BESS_WEB_DIR=/app/web

USER app

EXPOSE 8000

CMD ["pv-bess", "serve", "--host", "0.0.0.0", "--port", "8000"]
