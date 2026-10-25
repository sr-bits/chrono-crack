"""ChronoCrack - recupera a chave AES-256 de um software que semeia o RNG com o tempo Unix."""

from .attack import crack, split_message, benchmark, SearchResult

__all__ = ["crack", "split_message", "benchmark", "SearchResult"]
