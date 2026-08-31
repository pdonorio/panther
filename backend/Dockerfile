# Immagine del backend. Contesto di build = radice del repo, perché il backend
# importerà i parser da pipeline/ (fase 1) e deve poterli copiare.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY backend/pyproject.toml /srv/backend/
COPY backend/app /srv/backend/app
COPY backend/alembic /srv/backend/alembic
COPY backend/alembic.ini /srv/backend/

RUN pip install --no-cache-dir -e /srv/backend

# Utente non privilegiato: il processo non ha motivo di essere root, e un ente
# che ospita l'applicazione lo chiederà comunque.
RUN useradd --create-home --uid 10001 panther
USER panther

WORKDIR /srv/backend
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
