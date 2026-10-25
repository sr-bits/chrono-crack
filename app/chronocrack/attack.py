"""
Nucleo do ataque ChronoCrack.

O software-alvo cifra com AES-256 em modo CTR, mas gera a chave assim:

    import random
    random.seed(T)              # T = tempo Unix, em segundos, do envio
    key = random.randbytes(32)  # chave AES-256

A chave fica totalmente determinada pelo relogio. Conhecendo o intervalo de
tempo do envio, o espaco de chaves colapsa de 2**256 para o numero de segundos
desse intervalo (uma mensagem enviada num dia => 86 400 chaves possiveis).

O ataque percorre cada segundo candidato, recria a chave e tenta decifrar.
Como se conhece o inicio do texto em claro ("Ponto de encontro:"), basta
verificar se o decifrado comeca por essa frase para saber que a chave e a certa.
"""

from __future__ import annotations

import base64
import math
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Prefixo conhecido do texto em claro (ataque de texto em claro conhecido).
DEFAULT_CRIB = b"Ponto de encontro:"

# Intervalo indicado pelos metadados: 12 de novembro de 2025 (hora de Lisboa),
# convertido para tempo Unix em segundos (inclusive).
DEFAULT_LO = 1762905600
DEFAULT_HI = 1762991999

IV_LEN = 16  # o modo CTR usa um bloco contador inicial de 16 bytes


class CrackError(ValueError):
    """Entrada invalida (Base64 malformado, mensagem curta demais, etc.)."""


@dataclass
class SearchResult:
    """Resultado de uma tentativa de recuperacao."""

    found: bool
    seeds_tried: int
    elapsed_s: float
    range_lo: int
    range_hi: int
    seed: Optional[int] = None
    key_hex: Optional[str] = None
    seed_utc: Optional[str] = None
    iv_hex: Optional[str] = None
    ct_len: Optional[int] = None
    plaintext: Optional[str] = None
    plaintext_bytes_hex: Optional[str] = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def split_message(b64_message: str) -> tuple[bytes, bytes]:
    """Descodifica a mensagem Base64 e separa IV (16 bytes) do criptograma.

    A mensagem tem a forma Base64(IV || criptograma).
    """
    cleaned = "".join(b64_message.split())
    try:
        blob = base64.b64decode(cleaned, validate=True)
    except (ValueError, Exception) as exc:  # noqa: BLE001 - base64 lanca varios tipos
        raise CrackError(f"Base64 invalido: {exc}") from exc
    if len(blob) <= IV_LEN:
        raise CrackError(
            f"Mensagem curta demais: {len(blob)} bytes (precisa de > {IV_LEN})."
        )
    return blob[:IV_LEN], blob[IV_LEN:]


def _key_from_seed(seed: int) -> bytes:
    """Reproduz exatamente a geracao de chave do software-alvo."""
    rng = random.Random()
    rng.seed(seed)
    return rng.randbytes(32)


def _decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    return decryptor.update(ct) + decryptor.finalize()


def crack(
    b64_message: str,
    lo: int = DEFAULT_LO,
    hi: int = DEFAULT_HI,
    crib: bytes = DEFAULT_CRIB,
    progress: Optional[Callable[[int, int], None]] = None,
    progress_every: int = 2000,
) -> SearchResult:
    """Percorre o intervalo de seeds e devolve o resultado.

    progress, se fornecido, e chamado como progress(seeds_tried, total) de tempos
    a tempos para alimentar uma barra de progresso.
    """
    if lo > hi:
        raise CrackError("Intervalo invalido: lo > hi.")

    iv, ct = split_message(b64_message)
    total = hi - lo + 1
    crib_len = min(len(crib), len(ct))
    t0 = time.perf_counter()

    tried = 0
    for seed in range(lo, hi + 1):
        tried += 1
        key = _key_from_seed(seed)
        # So decifra o cabecalho primeiro (barato) antes de validar o crib.
        head = _decrypt(key, iv, ct[:crib_len])
        if head == crib[:crib_len]:
            pt = _decrypt(key, iv, ct)
            elapsed = time.perf_counter() - t0
            if progress:
                progress(tried, total)
            return SearchResult(
                found=True,
                seeds_tried=tried,
                elapsed_s=elapsed,
                range_lo=lo,
                range_hi=hi,
                seed=seed,
                key_hex=key.hex(),
                seed_utc=datetime.fromtimestamp(seed, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                ),
                iv_hex=iv.hex(),
                ct_len=len(ct),
                plaintext=pt.decode("utf-8", errors="replace"),
                plaintext_bytes_hex=pt.hex(),
            )
        if progress and tried % progress_every == 0:
            progress(tried, total)

    elapsed = time.perf_counter() - t0
    if progress:
        progress(tried, total)
    return SearchResult(
        found=False,
        seeds_tried=tried,
        elapsed_s=elapsed,
        range_lo=lo,
        range_hi=hi,
        iv_hex=iv.hex(),
        ct_len=len(ct),
        errors=["Nenhum seed no intervalo produziu o prefixo conhecido."],
    )


# ---------------------------------------------------------------------------
# Comparacao academica: como escala o custo do bruteforce com a janela de
# incerteza (dia / semana / mes / ano). O ponto a demonstrar e que o custo
# cresce apenas LINEARMENTE com o numero de segundos, pelo que alargar a
# janela de um dia para um ano e praticamente irrelevante face a 2**256.
# ---------------------------------------------------------------------------

# (rotulo, numero de segundos da janela)
SCALES = [
    ("Dia", 86_400),
    ("Semana", 7 * 86_400),
    ("Mês", 30 * 86_400),
    ("Ano", 365 * 86_400),
]

# Debito medido varrendo integralmente a janela de um dia (o caso real); as
# janelas maiores sao projetadas a partir desse debito, por o custo crescer
# linearmente com o numero de seeds.
BENCH_SAMPLE = 86_400

AES256_SPACE = 2 ** 256


def _measure_rate(iv: bytes, ct: bytes, n: int) -> float:
    """Mede o debito (seeds/s) varrendo n seeds com o trabalho real por seed.

    Faz geracao de chave + uma decifra de bloco por seed, sem sair mais cedo,
    para obter um debito representativo do ataque.
    """
    crib_len = min(len(DEFAULT_CRIB), len(ct)) or 1
    t0 = time.perf_counter()
    for seed in range(DEFAULT_LO, DEFAULT_LO + n):
        key = _key_from_seed(seed)
        _decrypt(key, iv, ct[:crib_len])
    elapsed = time.perf_counter() - t0
    return n / elapsed if elapsed > 0 else float("inf")


def benchmark(b64_message: str, scales=SCALES, sample: int = BENCH_SAMPLE) -> dict:
    """Compara o custo do bruteforce para varias janelas de incerteza.

    Mede o debito real varrendo a janela de um dia e projeta, para cada janela,
    o tempo para varrer todo o espaco e o tempo medio esperado ate encontrar a
    chave (metade do varrimento). Inclui a comparacao com o espaco do AES-256.
    """
    iv, ct = split_message(b64_message)
    rate = _measure_rate(iv, ct, sample)  # seeds/s (medido no caso real: 1 dia)
    results = []
    for label, span in scales:
        scan_s = span / rate if rate > 0 else float("inf")
        results.append(
            {
                "label": label,
                "span": span,
                "measured": span <= sample,  # True = tamanho igual ao medido
                "rate": rate,
                "scan_s": scan_s,
                "expected_find_s": scan_s / 2,
                "log2_space": math.log2(span),
            }
        )
    return {
        "results": results,
        "aes256": {
            "log2_space": 256,
            "space_sci": "1.16e77",
            "scan_s": AES256_SPACE / rate if rate > 0 else float("inf"),
        },
        "avg_rate": rate,
    }
