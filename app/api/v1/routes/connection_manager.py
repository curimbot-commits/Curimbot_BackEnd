"""
ConnectionManager: registra y gestiona WebSockets activos.
Las conexiones viven en memoria del proceso (no en Redis) porque
los objetos WebSocket no son serializables.
Para broadcast cross-worker se usa Redis Pub/Sub.
"""

import asyncio
import logging
from typing import Dict, Optional
import uuid

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Gestiona conexiones WebSocket activas en el proceso actual.
    Thread-safe mediante asyncio.Lock.
    
    Para entornos multi-worker, el broadcast cross-worker se delega
    a Redis Pub/Sub — cada worker tiene su propio ConnectionManager.
    """

    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> str:
        connection_id = str(uuid.uuid4())[:8]
        async with self._lock:
            self._connections[connection_id] = websocket
        logger.info(f"[CM] Registrado {connection_id}. Total: {len(self._connections)}")
        return connection_id

    async def unregister(self, connection_id: str) -> None:
        async with self._lock:
            self._connections.pop(connection_id, None)
        logger.info(f"[CM] Eliminado {connection_id}. Total: {len(self._connections)}")

    async def broadcast(self, payload: dict) -> int:
        """Broadcast a todas las conexiones del proceso actual."""
        async with self._lock:
            targets = list(self._connections.items())

        sent = 0
        failed_ids = []

        for conn_id, ws in targets:
            try:
                await ws.send_json(payload)
                sent += 1
            except Exception:
                failed_ids.append(conn_id)

        # Limpiar conexiones rotas
        for conn_id in failed_ids:
            await self.unregister(conn_id)

        return sent

    @property
    def active_count(self) -> int:
        return len(self._connections)


# Singleton de proceso
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager