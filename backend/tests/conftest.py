import tempfile
from pathlib import Path

import pytest

from app.config import settings


@pytest.fixture()
def temp_db():
    """Point the app at a throwaway SQLite file for the duration of a test."""
    from app import db, store

    d = tempfile.mkdtemp()
    path = str(Path(d) / "test.db")
    old = settings.db_path
    settings.db_path = path
    db.init_db()
    yield path
    settings.db_path = old
