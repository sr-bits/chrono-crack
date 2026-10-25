# syntax=docker/dockerfile:1

# ---- Estagio 1: build das dependencias ----
FROM python:3.13.1-alpine3.21 AS builder

# Virtualenv autossuficiente: copia-se inteiro para o estagio final.
ENV VENV=/opt/venv
RUN python -m venv "$VENV"
ENV PATH="$VENV/bin:${PATH}"

WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Estagio 2: imagem final ----
FROM python:3.13.1-alpine3.21 AS runtime

# Utilizador nao-root.
RUN addgroup -S app && adduser -S app -G app

ENV VENV=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /srv

# Virtualenv com as dependencias, vindo do estagio de build.
COPY --from=builder /opt/venv /opt/venv
# Codigo da aplicacao.
COPY app/ /srv/

USER app
EXPOSE 8000

# Healthcheck: o endpoint /healthz responde 200 quando a app esta de pe.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else sys.exit(1)"

# gunicorn com worker de threads para suportar o streaming SSE concorrente.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", \
     "--workers", "2", "--threads", "4", "--timeout", "120", "app:app"]
