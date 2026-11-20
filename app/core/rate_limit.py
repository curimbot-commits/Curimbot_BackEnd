"""
Rate limiting mínimo en memoria (ventana deslizante por IP y endpoint).

Uso como dependencia de FastAPI, sin cambiar la firma del endpoint:

    @router.post("/login", dependencies=[Depends(rate_limit(10, 60))])

Limitaciones conocidas (aceptables con un solo proceso uvicorn):
- El estado vive en memoria del proceso: con varios workers cada uno lleva
  su propia cuenta. Si se escala, mover el contador a Redis.
- La IP se toma de `request.client.host`. Detrás de un proxy (Traefik en
  Dokploy) uvicorn debe ejecutarse con --proxy-headers y FORWARDED_ALLOW_IPS
  para que sea la IP real del cliente y no la del proxy.

Se desactiva con RATE_LIMIT_ENABLED=false (por ejemplo, en los tests).
"""

import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status

_hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in ("0", "false", "no")


def reset() -> None:
    """Vacía los contadores (útil en tests)."""
    with _lock:
        _hits.clear()


def rate_limit(max_requests: int, window_seconds: int):
    """Crea una dependencia que permite `max_requests` por `window_seconds` por IP."""

    def dependency(request: Request) -> None:
        if not _enabled():
            return
        client_ip = request.client.host if request.client else "unknown"
        key = (request.url.path, client_ip)
        now = time.monotonic()
        with _lock:
            hits = _hits[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= max_requests:
                retry_after = int(window_seconds - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Demasiadas solicitudes. Intenta de nuevo más tarde.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

    return dependency
