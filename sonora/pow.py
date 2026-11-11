"""Verificación (proof-of-work) que LRCLIB exige antes de publicar una letra.

Se busca un número (nonce) tal que SHA-256(prefijo + nonce) <= objetivo, igual que LRCGET.
El trabajo se reparte entre varios procesos para que tarde segundos y no congele la interfaz.
Este módulo no importa Qt a propósito: cada proceso hijo lo carga y debe arrancar rápido.
"""
import hashlib
import multiprocessing as mp
import os
import time

CHUNK = 20000


def _worker(prefix: str, target: bytes, start: int, step: int, found, stop):
    base = hashlib.sha256(prefix.encode())
    n = start
    while not stop.is_set():
        for _ in range(CHUNK):
            h = base.copy()
            h.update(str(n).encode())
            if h.digest() <= target:
                found.put(n)
                stop.set()
                return
            n += step


def solve(prefix: str, target_hex: str, cancelled=lambda: False, workers: int | None = None) -> str | None:
    """Devuelve el nonce como texto, o None si se canceló."""
    target = bytes.fromhex(target_hex)
    k = workers or max(1, (os.cpu_count() or 2) - 1)
    ctx = mp.get_context("spawn")
    found, stop = ctx.Queue(), ctx.Event()
    procs = [ctx.Process(target=_worker, args=(prefix, target, i, k, found, stop), daemon=True)
             for i in range(k)]
    for p in procs:
        p.start()
    try:
        while True:
            try:
                return str(found.get(timeout=0.3))
            except Exception:  # queue.Empty
                if cancelled():
                    return None
                if not any(p.is_alive() for p in procs) and found.empty():
                    raise RuntimeError("Los procesos de verificación terminaron sin resultado")
    finally:
        stop.set()
        deadline = time.monotonic() + 2
        for p in procs:
            p.join(max(0.0, deadline - time.monotonic()))
            if p.is_alive():
                p.terminate()


def verify(prefix: str, target_hex: str, nonce: str) -> bool:
    return hashlib.sha256((prefix + nonce).encode()).digest() <= bytes.fromhex(target_hex)
