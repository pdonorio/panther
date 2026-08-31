"""Configurazione, letta dall'ambiente.

Niente valori di produzione scritti nel codice: l'applicazione va consegnata a
un ente e deve girare altrove senza modifiche al sorgente (vedi next.yaml,
criterio della portabilità).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Impostazioni(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PANTHER_", env_file=".env", extra="ignore")

    # URL sincrono: il backend usa SQLAlchemy sync, non async. La scelta è
    # deliberata — il carico è una manciata di utenti e il codice sincrono è
    # molto più facile da leggere e da consegnare a qualcun altro.
    database_url: str = "postgresql+psycopg://panther:panther@localhost:5432/panther"

    # Origini ammesse per il frontend. In sviluppo Vite serve su 5173.
    cors_origins: list[str] = ["http://localhost:5173"]

    debug: bool = False


@lru_cache
def impostazioni() -> Impostazioni:
    """Istanza unica: la configurazione si legge una volta sola all'avvio."""
    return Impostazioni()
