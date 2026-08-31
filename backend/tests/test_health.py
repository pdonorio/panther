"""Test del controllo di salute.

Il caso che conta davvero è il secondo: quando Postgres non risponde il codice
HTTP deve essere 503. Un 200 con un campo «degradato» convincerebbe qualunque
orchestratore che il servizio sta bene.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import sessione
from app.main import app
from tests.conftest import richiede_db


@richiede_db
def test_salute_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"stato": "ok", "database": "ok"}


class _SessioneIrraggiungibile:
    """Sta in piedi ma muore su qualunque query, come un Postgres spento."""

    def execute(self, *_: object, **__: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connessione rifiutata"))


@pytest.fixture
def client_senza_db() -> Iterator[TestClient]:
    app.dependency_overrides[sessione] = lambda: _SessioneIrraggiungibile()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_salute_senza_database_risponde_503(client_senza_db: TestClient) -> None:
    """Regressione: il database giù deve essere 503, non 200."""
    r = client_senza_db.get("/health")
    assert r.status_code == 503
    assert r.json()["database"] == "irraggiungibile"
