"""Applicazione FastAPI.

Fase 0: solo lo scheletro e il controllo di salute. Le rotte vere arrivano
con le fasi successive (schema e ingest, auth, lettura, modulistica).
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import impostazioni
from .db import sessione

log = logging.getLogger(__name__)

app = FastAPI(
    title="Panther",
    description="Backend del toolkit operativo. Non è fonte ufficiale: "
    "il testo che fa fede è quello pubblicato in Gazzetta Ufficiale.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=impostazioni().cors_origins,
    # I cookie di sessione viaggiano cross-origin in sviluppo (Vite su 5173,
    # API su 8000): senza questo il browser non li manda.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def salute(db: Session = Depends(sessione)) -> JSONResponse:
    """Salute del servizio, database compreso.

    Un health check che non tocca il database mente: il processo può stare in
    piedi mentre Postgres è irraggiungibile, ed è esattamente il caso in cui
    l'orchestratore deve accorgersene.

    Se il database non risponde il codice è 503, non 200 con un campo che dice
    «degradato»: chi controlla la salute guarda lo stato HTTP, non il corpo, e
    un 200 lo convincerebbe che va tutto bene.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        log.warning("health: database irraggiungibile (%s)", e)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"stato": "degradato", "database": "irraggiungibile"},
        )
    return JSONResponse(content={"stato": "ok", "database": "ok"})
