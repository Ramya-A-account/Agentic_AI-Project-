"""
AgentCare RAG Retriever

This is the "R" in RAG: before the Recommendation Agent asks an LLM to
reason about an incident, this module retrieves the most relevant
hospital policy/SOP document from agentcare/knowledge_base/ and hands
it to the LLM as grounding context. The LLM's recommendation is then
based on an actual retrieved document, not free-floating reasoning —
and which document was retrieved is recorded for auditability.

Design principles (same as llm_reasoning.py):
  - Fully offline, zero API cost, zero network dependency. Retrieval
    uses TF-IDF + cosine similarity (scikit-learn), not an embedding
    API call — this makes it fast and reliable even with no internet,
    which matters when the LLM call itself is already network-dependent.
  - Never crash the pipeline. If scikit-learn isn't installed, or the
    knowledge base is empty/unreadable, retrieval returns None and the
    caller proceeds without grounding (same graceful-degradation pattern
    as the LLM layer).
"""

import os

KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge_base")

_documents = None       # list of {"title": ..., "text": ...}
_vectorizer = None
_doc_vectors = None
_load_attempted = False


def _title_from_filename(filename):
    name = os.path.splitext(filename)[0]
    return name.replace("_", " ").title()


def _load_documents():
    """Load every .md/.txt file in the knowledge base directory. Cached
    after the first call — the knowledge base doesn't change at runtime."""
    global _documents

    if _documents is not None:
        return _documents

    documents = []

    try:
        for filename in sorted(os.listdir(KNOWLEDGE_BASE_DIR)):
            if not filename.endswith((".md", ".txt")):
                continue
            path = os.path.join(KNOWLEDGE_BASE_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            documents.append({"title": _title_from_filename(filename), "text": text})
    except Exception as exc:
        print(f"⚠️  RAG knowledge base could not be loaded: {exc}")
        documents = []

    _documents = documents
    return _documents


def _build_index():
    """Build the TF-IDF index over the knowledge base. Returns False if
    scikit-learn isn't available or there are no documents to index."""
    global _vectorizer, _doc_vectors, _load_attempted

    if _load_attempted:
        return _vectorizer is not None

    _load_attempted = True

    documents = _load_documents()
    if not documents:
        return False

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        _vectorizer = TfidfVectorizer(stop_words="english")
        _doc_vectors = _vectorizer.fit_transform([doc["text"] for doc in documents])
        return True
    except Exception as exc:
        print(f"⚠️  RAG retrieval disabled — could not build index: {exc}")
        _vectorizer = None
        return False


def retrieve(query, top_k=1, min_score=0.05):
    """
    Retrieve the most relevant knowledge base document(s) for a query.

    Returns a list of {"title", "text", "score"} dicts, best match
    first, or an empty list if retrieval isn't available or nothing
    scored above min_score. Never raises — callers can treat an empty
    list the same as "no relevant policy found."
    """
    if not _build_index():
        return []

    try:
        from sklearn.metrics.pairwise import cosine_similarity

        documents = _load_documents()
        query_vector = _vectorizer.transform([query])
        scores = cosine_similarity(query_vector, _doc_vectors)[0]

        ranked = sorted(
            zip(documents, scores), key=lambda pair: pair[1], reverse=True
        )

        return [
            {"title": doc["title"], "text": doc["text"], "score": float(score)}
            for doc, score in ranked[:top_k]
            if score >= min_score
        ]
    except Exception as exc:
        print(f"⚠️  RAG retrieval failed: {exc}")
        return []


def is_available():
    return _build_index()
