"""Client per le API OpenData di Normattiva.

Base URL e contratto verificati il 2026-08-18 — vedi docs/data-sources.md.
Nessuna autenticazione richiesta.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1"

# Vigenza (parametro `formatoRichiesta`)
VIGENZA_ORIGINALE = "O"
VIGENZA_MULTIVIGENTE = "M"
VIGENZA_VIGENTE = "V"

# Formato file (parametro `formato`)
FORMATO_XML = "XML"
FORMATO_AKN = "AKN"
FORMATO_JSON = "JSON"

# Directory dei due codici dentro lo ZIP della collezione "Codici".
# Lo ZIP non ha un manifest: l'atto si identifica dal nome directory.
DIR_CODICE_PENALE = "REGIO DECRETO_19301019_1398"
DIR_CODICE_STRADA = "DECRETO LEGISLATIVO_19920430_285"


@dataclass(frozen=True)
class Collezione:
    nome: str
    vigenza: str
    descrizione_vigenza: str
    data_creazione: str
    numero_atti: int

    @classmethod
    def from_api(cls, d: dict) -> Collezione:
        return cls(
            nome=d["nomeCollezione"],
            vigenza=d["formatoCollezione"],
            descrizione_vigenza=d.get("descrizioneFormatoCollezione", ""),
            data_creazione=d.get("dataCreazione", ""),
            numero_atti=d.get("numeroAtti", 0),
        )


class NormattivaError(RuntimeError):
    pass


class NormattivaClient:
    """Wrapper minimale con retry/backoff.

    L'API non documenta rate limit; il backoff è prudenziale, non prescritto.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 300.0,
        max_retries: int = 4,
    ) -> None:
        self._max_retries = max_retries
        # follow_redirects è OBBLIGATORIO: il download risponde 302 verso un
        # URL firmato monouso su .../file-download/v1/download/<token>.
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "panther-pipeline/0.1 (+https://github.com/pdonorio/panther)"},
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kw: object) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                r = self._client.request(method, path, **kw)  # type: ignore[arg-type]
                if r.status_code == 429 or r.status_code >= 500:
                    raise NormattivaError(f"{r.status_code} su {path}")
                if r.status_code >= 400:
                    # 4xx client-side: inutile ritentare, il body spiega il perché.
                    raise NormattivaError(f"{r.status_code} su {path}: {r.text[:300]}")
                return r
            except (httpx.TransportError, NormattivaError) as e:
                last = e
                if attempt == self._max_retries - 1:
                    break
                delay = 2**attempt
                log.warning("tentativo %d fallito (%s), riprovo fra %ds", attempt + 1, e, delay)
                time.sleep(delay)
        raise NormattivaError(f"esaurito i tentativi su {path}") from last

    # --- lettura -----------------------------------------------------------

    def collezioni_predefinite(self) -> list[Collezione]:
        r = self._request("GET", "/api/v1/collections/collection-predefinite")
        return [Collezione.from_api(d) for d in r.json()]

    def atti_aggiornati(self, dal: str, al: str) -> list[dict]:
        """Atti modificati nell'intervallo. Date ISO-8601 (date-time).

        È l'endpoint per il sync incrementale notturno: evita di riscaricare
        i 6.9MB della collezione quando nulla è cambiato.
        """
        r = self._request(
            "POST",
            "/api/v1/ricerca/aggiornati",
            json={"dataInizioAggiornamento": dal, "dataFineAggiornamento": al},
        )
        return r.json()

    def dettaglio_atto_urn(self, urn: str) -> dict:
        r = self._request("POST", "/api/v1/atto/dettaglio-atto-urn", json={"urn": urn})
        return r.json()

    # --- bulk --------------------------------------------------------------

    def scarica_collezione(
        self,
        nome: str = "Codici",
        formato: str = FORMATO_XML,
        vigenza: str = VIGENZA_VIGENTE,
    ) -> bytes:
        """Scarica una collezione preconfezionata come ZIP.

        ATTENZIONE ai nomi dei parametri, sono controintuitivi:
          - `formato`          = formato FILE   (XML/AKN/JSON/PDF/...)
          - `formatoRichiesta` = VIGENZA        (O/M/V)
        Invertirli restituisce 400 con code 1006.
        """
        r = self._request(
            "GET",
            "/api/v1/collections/download/collection-preconfezionata",
            params={"nome": nome, "formato": formato, "formatoRichiesta": vigenza},
        )
        return r.content

    def scarica_codici(self, dest: Path) -> dict[str, Path]:
        """Scarica la collezione «Codici» ed estrae i due atti che ci servono.

        Ritorna {'reati_cp': path, 'cds': path}.
        """
        dest.mkdir(parents=True, exist_ok=True)
        blob = self.scarica_collezione("Codici", FORMATO_XML, VIGENZA_VIGENTE)
        log.info("collezione Codici: %.1f MB", len(blob) / 1024 / 1024)

        out: dict[str, Path] = {}
        wanted = {DIR_CODICE_PENALE: "reati_cp", DIR_CODICE_STRADA: "cds"}

        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                head = info.filename.split("/", 1)[0]
                key = wanted.get(head)
                if key is None:
                    continue
                target = dest / f"{key}.xml"
                target.write_bytes(zf.read(info))
                out[key] = target
                log.info("estratto %s -> %s (%d byte)", key, target.name, target.stat().st_size)

        missing = set(wanted.values()) - set(out)
        if missing:
            raise NormattivaError(
                f"atti non trovati nella collezione: {sorted(missing)}. "
                "I nomi directory dello ZIP potrebbero essere cambiati."
            )
        return out
