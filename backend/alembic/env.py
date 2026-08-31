"""Ambiente Alembic.

L'URL del database arriva dalla configurazione dell'applicazione, non da
alembic.ini: una sola fonte, e le migrazioni girano in produzione con le stesse
variabili d'ambiente del servizio.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import impostazioni
from app.db import Base

# Importa i modelli perché Base.metadata sia popolata: senza, l'autogenerate
# produce migrazioni vuote. Ogni modello nuovo va esportato da app.models.
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", impostazioni().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migrazioni_offline() -> None:
    """Genera SQL senza connettersi — utile per farsi rivedere una migrazione."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def migrazioni_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Senza questo Alembic non si accorge dei cambi di tipo su una
            # colonna esistente e la migrazione esce incompleta.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    migrazioni_offline()
else:
    migrazioni_online()
