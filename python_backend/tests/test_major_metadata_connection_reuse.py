import asyncio
import pytest
from pathlib import Path
from storage.metadata import MetadataStore


@pytest.mark.asyncio
async def test_metadata_store_sqlite_connection_reuse(tmp_path: Path):
    db_path = tmp_path / "metadata_test.db"
    store = MetadataStore()
    store.backend_type = "sqlite"
    store.sqlite_path = db_path

    await store.setup()
    initial_conn = store._sqlite_conn
    assert initial_conn is not None

    async def op(idx: int):
        await store.set_label(f"thread_{idx % 10}", f"cp_{idx}", f"Label {idx}")
        labels = await store.get_labels(f"thread_{idx % 10}")
        assert labels.get(f"cp_{idx}") == f"Label {idx}"

    # Run 100 metadata operations concurrently
    tasks = [op(i) for i in range(100)]
    await asyncio.gather(*tasks)

    # Verify the same connection object was reused for all 100 operations
    assert store._sqlite_conn is initial_conn

    # Verify close cleans it up
    await store.close()
    assert store._sqlite_conn is None
