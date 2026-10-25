# ChronoCrack

Prototipo didatico que recupera a chave AES-256 de um software de mensagens cuja
chave e gerada a partir do **tempo Unix** (`random.seed(T)` + `random.randbytes(32)`).

Por o relogio determinar totalmente a chave, o espaco de chaves do AES-256 colapsa
de `2^256` para o numero de segundos do intervalo de envio. Conhecendo o dia do
envio (86 400 segundos) e o inicio do texto em claro (`"Ponto de encontro:"`), a
chave recupera-se em fracoes de segundo.

A interface web mostra, passo a passo: a separacao `IV || criptograma`, a procura
do seed em tempo real e o texto em claro recuperado. Inclui ainda uma
**comparacao academica** que mede o debito do ataque e projeta o custo da forca
bruta para janelas de incerteza de dia, semana, mes e ano, contrastando-o com o
espaco completo do AES-256 (`POST /api/benchmark`).

## Arquitetura

```
  browser ──http──> nginx (proxy, rede "edge") ──> web (Flask + gunicorn, rede "internal")
```

- **web** — Flask + gunicorn (worker `gthread`), nao-root, com `/healthz`.
- **nginx** — proxy reverso; desliga o buffering em `/api/crack-stream` (SSE).
- Segredos/config via `.env` (ver `.env.example`), nunca na imagem.

| Ficheiro | Papel |
|----------|-------|
| `app/chronocrack/attack.py` | nucleo do ataque (sem dependencia de Flask) |
| `app/app.py` | servidor Flask e endpoints |
| `app/templates/`, `app/static/` | interface web |
| `Dockerfile` | build multi-stage, imagem final alpine, utilizador nao-root |
| `docker-compose.yml` | servicos `web` + `nginx`, healthchecks |
| `nginx/nginx.conf` | proxy reverso com suporte a SSE |

## Deploy (passos para handoff)

Pre-requisitos: Docker e Docker Compose.

```bash
# 1. Configurar o ambiente
cp .env.example .env            # ajustar HTTP_PORT se necessario

# 2. Criar a rede externa partilhada (convencao do repo), se ainda nao existir
docker network create edge || true

# 3. Construir e arrancar
docker compose up -d --build

# 4. Confirmar que esta de pe
docker compose ps              # ambos os servicos "healthy"
curl http://localhost:8080/healthz
```

Abrir **http://localhost:8080** no browser. Colar a mensagem Base64, confirmar o
intervalo de tempo Unix e clicar em **Iniciar ataque**.

Parar: `docker compose down`.

## Utilizacao sem containers (desenvolvimento)

```bash
cd app
python -m pip install -r requirements.txt
python app.py                  # http://localhost:8000
```

Ataque direto pela linha de comandos (sem servidor):

```bash
cd app
python -c "from chronocrack import crack; r=crack(open('../msg.txt').read()); print(r.plaintext)"
```

## A falha e a correcao

- **Falha:** a chave e derivada de `random.seed(tempo_unix)`, um PRNG
  (Mersenne Twister) nao criptografico semeado com um valor de baixa entropia e
  previsivel. O atacante nao ataca o AES; apenas enumera os seeds possiveis.
- **Correcao:** gerar a chave com um CSPRNG, por exemplo
  `key = secrets.token_bytes(32)` ou `os.urandom(32)`, independente do relogio.
  Nunca semear um PRNG com tempo/PID para material criptografico.

> Prototipo academico (ISCTE, Criptografia). Uso exclusivamente educativo.
