"""Fixture condivise.

I test girano contro un Postgres vero, non SQLite in memoria: metà di ciò che
questo backend deve fare (unaccent, tsvector, vincoli) è comportamento Postgres,
e un doppio in memoria lo nasconderebbe fino alla produzione.

In locale: `docker compose up -d db`. In CI: container di servizio.
Senza database i test si auto-skippano, così la suite gira comunque.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import motore
from app.main import app


def _database_raggiungibile() -> bool:
    try:
        with motore.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


richiede_db = pytest.mark.skipif(
    not _database_raggiungibile(),
    reason="Postgres non raggiungibile: `docker compose up -d db`",
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
