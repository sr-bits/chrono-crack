"""
Servidor Flask do ChronoCrack.

Expoe uma interface web para visualizar o ataque: cola-se a mensagem Base64,
define-se o intervalo de tempo Unix e observa-se, em tempo real, a procura do
seed correto ate recuperar o texto em claro.
"""

from __future__ import annotations

import json
import os
import time

from flask import Flask, Response, jsonify, render_template, request

from chronocrack.attack import (
    DEFAULT_CRIB,
    DEFAULT_HI,
    DEFAULT_LO,
    CrackError,
    benchmark,
    crack,
    split_message,
)

# Mensagem intercetada fornecida no enunciado (valor por omissao da interface).
SAMPLE_MESSAGE = (
    "ht1XeG5JhC5ch2+6PO4OlFZk1MZLGSFV/qPi+i+a2q0c6mKyvknVrB9QTHu5aibmaYJw2W+7KoeHyOk7"
    "XhvDjZG9h07Si3Jaif2lzfs2CITmi3BHFaeT5NgKTEGB1rLB60ZBsF9XW8fLW+ZMbG1s149mF8tsubw"
    "q1zUkfgwSIuCN7UdoKyooNiEyyKdSOCnJ29NlvSoDTab4+nSTqrX2ALbejBfG34QWk7NwtW+XdYRYoic"
    "rLgFrl75h2qwfBcTCrTrMczeTy533n2gL0XoLgB2hPV+rBLseqfnLCS92wxiD29bJ5EtwX8ff1THxFk5"
    "14A=="
)

MAX_RANGE = int(os.environ.get("CHRONOCRACK_MAX_RANGE", "5000000"))

app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "index.html",
        sample_message=SAMPLE_MESSAGE,
        default_lo=DEFAULT_LO,
        default_hi=DEFAULT_HI,
        default_crib=DEFAULT_CRIB.decode("utf-8"),
    )


@app.route("/healthz")
def healthz():
    """Endpoint de healthcheck para o container."""
    return jsonify(status="ok"), 200


@app.route("/api/split", methods=["POST"])
def api_split():
    """Mostra como a mensagem se separa em IV e criptograma, sem decifrar."""
    data = request.get_json(silent=True) or {}
    try:
        iv, ct = split_message(data.get("message", ""))
    except CrackError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(iv_hex=iv.hex(), iv_len=len(iv), ct_len=len(ct))


def _parse_params(data: dict):
    message = (data.get("message") or "").strip()
    if not message:
        raise CrackError("Mensagem vazia.")
    try:
        lo = int(data.get("lo", DEFAULT_LO))
        hi = int(data.get("hi", DEFAULT_HI))
    except (TypeError, ValueError) as exc:
        raise CrackError("Intervalo de tempo invalido.") from exc
    if hi < lo:
        raise CrackError("Intervalo invalido: fim antes do inicio.")
    if hi - lo + 1 > MAX_RANGE:
        raise CrackError(
            f"Intervalo demasiado grande ({hi - lo + 1} segundos). "
            f"Maximo permitido: {MAX_RANGE}."
        )
    crib_text = data.get("crib")
    crib = crib_text.encode("utf-8") if crib_text else DEFAULT_CRIB
    return message, lo, hi, crib


@app.route("/api/benchmark", methods=["POST"])
def api_benchmark():
    """Compara o custo do bruteforce para janelas de dia/semana/mes/ano."""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify(error="Mensagem vazia."), 400
    try:
        result = benchmark(message)
    except CrackError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result)


@app.route("/api/crack", methods=["POST"])
def api_crack():
    """Executa o ataque e devolve o resultado completo em JSON (sincrono)."""
    data = request.get_json(silent=True) or {}
    try:
        message, lo, hi, crib = _parse_params(data)
        result = crack(message, lo=lo, hi=hi, crib=crib)
    except CrackError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result.to_dict())


@app.route("/api/crack-stream", methods=["POST"])
def api_crack_stream():
    """Executa o ataque emitindo progresso em tempo real via Server-Sent Events."""
    data = request.get_json(silent=True) or {}
    try:
        message, lo, hi, crib = _parse_params(data)
    except CrackError as exc:
        return jsonify(error=str(exc)), 400

    def generate():
        total = hi - lo + 1
        yield _sse("start", {"total": total, "lo": lo, "hi": hi})
        yield from _run_with_progress(message, lo, hi, crib)

    return Response(generate(), mimetype="text/event-stream")


def _run_with_progress(message, lo, hi, crib):
    """Gera eventos SSE enquanto percorre os seeds."""
    import random
    from datetime import datetime, timezone

    from chronocrack.attack import _decrypt  # reutiliza a decifra interna

    try:
        iv, ct = split_message(message)
    except CrackError as exc:
        yield _sse("error", {"message": str(exc)})
        return

    total = hi - lo + 1
    crib_len = min(len(crib), len(ct))
    t0 = time.perf_counter()
    last = t0
    tried = 0

    for seed in range(lo, hi + 1):
        tried += 1
        rng = random.Random()
        rng.seed(seed)
        key = rng.randbytes(32)
        head = _decrypt(key, iv, ct[:crib_len])
        if head == crib[:crib_len]:
            pt = _decrypt(key, iv, ct)
            elapsed = time.perf_counter() - t0
            yield _sse(
                "found",
                {
                    "seed": seed,
                    "seed_utc": datetime.fromtimestamp(seed, tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    ),
                    "key_hex": key.hex(),
                    "iv_hex": iv.hex(),
                    "ct_len": len(ct),
                    "seeds_tried": tried,
                    "total": total,
                    "elapsed_s": round(elapsed, 3),
                    "plaintext": pt.decode("utf-8", errors="replace"),
                },
            )
            return
        now = time.perf_counter()
        if now - last >= 0.1:
            last = now
            yield _sse("progress", {"tried": tried, "total": total})

    elapsed = time.perf_counter() - t0
    yield _sse(
        "notfound",
        {"seeds_tried": tried, "total": total, "elapsed_s": round(elapsed, 3)},
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
