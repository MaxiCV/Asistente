from contextlib import contextmanager

from qdrant_client import QdrantClient


@contextmanager
def qdrant_connection(url: str, *, timeout: int = 5):
    client = QdrantClient(url=url, timeout=timeout)
    try:
        yield client
    finally:
        client.close()
