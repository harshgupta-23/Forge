"""
ingestion.py — Document parsing, recursive chunking, and embedding ingestion pipeline.
"""

import os
import uuid
import pathlib
from typing import Optional, Callable, Any
from rag.embeddings import embedding_manager
from rag.vector_store import get_vector_store


def _recursive_split_text(text: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[str]:
    """
    Recursively splits text on natural paragraph/line/word boundaries
    while maintaining target size and overlap.
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    separators = ["\n\n", "\n", ";", ". ", " ", ""]
    
    def _split(t: str, sep_idx: int) -> list[str]:
        if len(t) <= chunk_size:
            return [t] if t.strip() else []
        if sep_idx >= len(separators):
            # Hard slice fallback
            chunks = []
            start = 0
            while start < len(t):
                end = min(start + chunk_size, len(t))
                chunks.append(t[start:end])
                start += chunk_size - chunk_overlap
            return chunks

        sep = separators[sep_idx]
        parts = t.split(sep) if sep else list(t)
        
        chunks = []
        current = ""

        for part in parts:
            candidate = current + (sep if current and sep else "") + part
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current.strip():
                    chunks.append(current.strip())
                if len(part) > chunk_size:
                    # Further split large sub-part with next separator
                    sub_chunks = _split(part, sep_idx + 1)
                    chunks.extend(sub_chunks)
                    current = ""
                else:
                    # Keep overlap from previous part if possible
                    overlap_seed = current[-chunk_overlap:] if len(current) >= chunk_overlap else current
                    current = overlap_seed + (sep if sep else "") + part if overlap_seed else part

        if current.strip():
            chunks.append(current.strip())

        return chunks

    return _split(text, 0)


async def ingest_file(
    file_path: str,
    session_id: str = "global",
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    progress_callback: Optional[Callable[[str, int, str, int], Any]] = None
) -> dict[str, Any]:
    """
    Parses, chunks, embeds, and indexes a file into the vector store.
    Invokes progress_callback(step, progress_pct, message, chunks_count).
    """
    p = pathlib.Path(file_path).resolve()
    filename = p.name

    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    # 1. Parsing
    if progress_callback:
        await progress_callback("parsing", 15, f"Reading {filename}...", 0)

    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = p.read_text(encoding="latin-1")
        except Exception as exc:
            raise ValueError(f"Unable to read file content: {exc}")

    # 2. Chunking
    raw_chunks = _recursive_split_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not raw_chunks:
        raw_chunks = [content[:chunk_size]] if content.strip() else []

    total_chunks = len(raw_chunks)
    if progress_callback:
        await progress_callback("embedding", 40, f"Generated {total_chunks} chunks. Embedding...", total_chunks)

    # 3. Batch Embedding
    chunk_dicts = []
    batch_size = 32
    embeddings = []

    for i in range(0, len(raw_chunks), batch_size):
        batch = raw_chunks[i:i + batch_size]
        batch_embs = await embedding_manager.embed_texts(batch)
        embeddings.extend(batch_embs)
        if progress_callback:
            pct = 40 + int((len(embeddings) / max(total_chunks, 1)) * 45)
            await progress_callback("embedding", min(pct, 85), f"Embedded {len(embeddings)}/{total_chunks} chunks...", total_chunks)

    for idx, (text_chunk, emb) in enumerate(zip(raw_chunks, embeddings)):
        chunk_dicts.append({
            "id": f"chunk_{uuid.uuid4().hex[:12]}",
            "session_id": session_id,
            "file_path": str(p),
            "filename": filename,
            "chunk_index": idx,
            "content": text_chunk,
            "embedding": emb,
            "metadata": {
                "file_extension": p.suffix,
                "file_size": p.stat().st_size,
                "char_length": len(text_chunk),
                "total_chunks": total_chunks,
                "model": embedding_manager.model_name
            }
        })

    # 4. Storage Ingestion
    store = get_vector_store()
    inserted_count = await store.add_chunks(chunk_dicts)

    if progress_callback:
        await progress_callback("indexed", 100, f"Indexed {inserted_count} chunks into vector store.", inserted_count)

    return {
        "filename": filename,
        "file_path": str(p),
        "chunks_count": inserted_count,
        "total_chars": len(content),
        "session_id": session_id
    }

