"""Motore e sessioni SQLAlchemy.

`Base` è la dichiarativa da cui discendono tutti i modelli: Alembic la importa
per l'autogenerazione delle migrazioni, quindi ogni modello nuovo va importato
in `app/models/__init__.py` o la migrazione non lo vedrà.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import impostazioni


class Base(DeclarativeBase):
    pass


# pool_pre_ping: un Postgres gestito chiude le connessioni inattive senza
# avvisare, e senza questo la prima query dopo una pausa muore con un errore
# di connessione invece di riaprire.
motore = create_engine(
    impostazioni().database_url,
    pool_pre_ping=True,
    echo=impostazioni().debug,
)

FabbricaSessioni = sessionmaker(bind=motore, autoflush=False, expire_on_commit=False)


def sessione() -> Iterator[Session]:
    """Dipendenza FastAPI: una sessione per richiesta, chiusa sempre."""
    with FabbricaSessioni() as s:
        yield s
