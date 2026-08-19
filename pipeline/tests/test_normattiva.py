"""Test del client Normattiva, senza rete.

Coprono soprattutto la validazione del payload: l'endpoint di download
risponde a intermittenza `200` con corpo vuoto, e quel caso deve essere un
errore ritentabile, non un BadZipFile a valle.
"""

from __future__ import annotations

import httpx
import pytest

from panther_pipeline.normattiva import (
    ZIP_MAGIC,
    NormattivaClient,
    NormattivaClientError,
    NormattivaError,
)

URL_DOWNLOAD = "/api/v1/collections/download/collection-preconfezionata"


def _client(handler: httpx.MockTransport, **kw: object) -> NormattivaClient:
    """Client con il trasporto sostituito, così non tocca la rete."""
    c = NormattivaClient(**kw)  # type: ignore[arg-type]
    c._client = httpx.Client(base_url=c._client.base_url, transport=handler)
    return c


def _zip_finto(n: int = 512) -> bytes:
    return ZIP_MAGIC + b"\x00" * n


def test_corpo_vuoto_viene_ritentato_e_poi_riesce() -> None:
    """Il caso reale: due risposte vuote, poi il file buono."""
    tentativi = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        tentativi["n"] += 1
        if tentativi["n"] <= 2:
            return httpx.Response(200, content=b"")
        return httpx.Response(200, content=_zip_finto())

    with _client(httpx.MockTransport(handler), max_retries=5, backoff=0) as c:
        blob = c.scarica_collezione()

    assert blob.startswith(ZIP_MAGIC)
    assert tentativi["n"] == 3


def test_corpo_vuoto_sempre_solleva() -> None:
    handler = httpx.MockTransport(lambda _: httpx.Response(200, content=b""))
    with _client(handler, max_retries=2, backoff=0) as c, pytest.raises(NormattivaError):
        c.scarica_collezione()


def test_payload_non_zip_riporta_la_diagnostica() -> None:
    """Se arriva HTML o JSON al posto dello ZIP, l'errore deve dirlo."""
    handler = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=b'{"error":"quota superata"}',
            headers={"content-type": "application/json"},
        )
    )
    with _client(handler, max_retries=1, backoff=0) as c, pytest.raises(NormattivaError) as e:
        c.scarica_collezione()

    msg = str(e.value)
    assert "non ZIP" in msg
    assert "quota superata" in msg


def test_zip_valido_passa_al_primo_colpo() -> None:
    tentativi = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        tentativi["n"] += 1
        return httpx.Response(200, content=_zip_finto())

    with _client(httpx.MockTransport(handler)) as c:
        assert c.scarica_collezione().startswith(ZIP_MAGIC)
    assert tentativi["n"] == 1


def test_4xx_non_viene_ritentato() -> None:
    """Un 400 (es. formato/vigenza invertiti) è un errore nostro: inutile insistere."""
    tentativi = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        tentativi["n"] += 1
        return httpx.Response(400, json={"code": 1006, "message": "formato non valido"})

    with (
        _client(httpx.MockTransport(handler), max_retries=4, backoff=0) as c,
        pytest.raises(NormattivaClientError, match="1006"),
    ):
        c.scarica_collezione()
    assert tentativi["n"] == 1
