from contextlib import contextmanager

from qdrant_client import QdrantClient


@contextmanager
def qdrant_connection(url: str, *, timeout: int = 5):
    # El SDK llama cloud_inference al envío de Document al servidor configurado,
    # también cuando ese servidor es nuestro Qdrant local. No contacta Qdrant Cloud.
    client = QdrantClient(url=url, timeout=timeout, cloud_inference=True)
    try:
        yield client
    finally:
        client.close()
