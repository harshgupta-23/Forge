import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from rag.ingestion import ingest_file


@pytest.mark.asyncio
async def test_ingest_file_exceeding_50mb_rejected(tmp_path: Path):
    large_file = tmp_path / "oversized.log"
    # Create sparse or stat-mocked file
    large_file.write_text("dummy")

    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 60 * 1024 * 1024  # 60MB
        mock_stat_res.st_mode = 0o100644  # regular file
        mock_stat.return_value = mock_stat_res

        with pytest.raises(ValueError, match="exceeds 50MB limit"):
            await ingest_file(str(large_file), session_id="test_session")


@pytest.mark.asyncio
async def test_ingest_file_within_limit(tmp_path: Path):
    small_file = tmp_path / "valid.txt"
    small_file.write_text("This is a small valid document for testing ingestion.")

    with patch("rag.ingestion.embedding_manager.embed_texts", return_value=[[0.1] * 768]), \
         patch("rag.ingestion.get_vector_store") as mock_vs:
        mock_store = MagicMock()
        mock_store.add_chunks = MagicMock(return_value=1)
        mock_vs.return_value = mock_store

        # Mock async add_chunks
        async def async_add_chunks(chunks):
            return len(chunks)
        mock_store.add_chunks = async_add_chunks

        res = await ingest_file(str(small_file), session_id="test_session")
        assert res["filename"] == "valid.txt"
        assert res["chunks_count"] >= 1
