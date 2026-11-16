from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode

from app.search.service import retrieve_passages


class CorpusRetriever(BaseRetriever):
    """Adapter over the existing ranked groups; never builds an index or embeddings."""

    def __init__(self, client, pinned, encoder, params, top_k):
        super().__init__()
        self.client, self.pinned, self.encoder = client, pinned, encoder
        self.params, self.top_k = params, top_k
        self.passages = []

    def _retrieve(self, query_bundle):
        params = self.params.model_copy(update={"q": query_bundle.query_str})
        self.passages = retrieve_passages(
            self.client, self.pinned, self.encoder, params, self.top_k
        )
        return [
            NodeWithScore(
                node=TextNode(
                    id_=str(item.passage.passage_id),
                    text=item.passage.text,
                    metadata={
                        "document_id": str(item.document.document_id),
                        "index_generation": self.pinned.generation_id,
                        "document_type": item.document.document_type,
                        "content_level": item.document.content_level,
                        "text_sha256": item.passage.text_sha256,
                        "title": item.document.title,
                    },
                    excluded_llm_metadata_keys=["text_sha256"],
                ),
                score=item.score,
            )
            for item in self.passages
        ]
