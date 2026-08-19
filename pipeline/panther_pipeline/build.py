"""Build degli artefatti dati di Panther.

    python -m panther_pipeline.build --out ../dist

Produce:
    dist/panther-core.db     tutti i campi operativi + FTS, SENZA testo integrale
    dist/testi/<tab>/<art>.json   testo integrale per articolo, fetch on-demand
    dist/manifest.json       dimensioni e hash, per la cache del client
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .normattiva import NormattivaClient
from .parsers import annex, structured
from .parsers.annex import Articolo

log = logging.getLogger(__name__)

SCHEMA = Path(__file__).with_name("schema.sql")

# Permalink stabile per articolo (fallback online).
URN_CP = "urn:nir:stato:regio.decreto:1930-10-19;1398"
URN_CDS = "urn:nir:stato:decreto.legislativo:1992-04-30;285"


def _permalink(urn: str, articolo: str) -> str:
    return f"https://www.normattiva.it/uri-res/N2Ls?{urn}~art{articolo}"


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _connect(path: Path) -> sqlite3.Connection:
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con


def _inserisci(
    con: sqlite3.Connection,
    tabella: str,
    articoli: list[Articolo],
    urn_atto: str,
    oggi: str,
) -> None:
    """Inserisce gli articoli SENZA testo integrale (resta NULL: vedi split)."""
    rows = [
        (
            i + 1,
            a.numero,
            a.rubrica,
            _permalink(urn_atto, a.numero),
            oggi,
            f"{urn_atto}~art{a.numero}",
            _hash(a.testo_integrale),
        )
        for i, a in enumerate(articoli)
    ]
    con.executemany(
        f"INSERT INTO {tabella} "
        "(id, articolo, titolo, testo_integrale_url, data_accesso, urn, hash_fonte) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    # content-table FTS: va popolata esplicitamente.
    con.execute(f"INSERT INTO {tabella}_fts({tabella}_fts) VALUES('rebuild')")
    log.info("%s: %d articoli", tabella, len(rows))


def _scrivi_testi(dest: Path, tabella: str, articoli: list[Articolo]) -> int:
    """Un JSON per articolo, servito on-demand da CloudFront."""
    d = dest / "testi" / tabella
    d.mkdir(parents=True, exist_ok=True)
    tot = 0
    for a in articoli:
        payload = {
            "articolo": a.numero,
            "rubrica": a.rubrica,
            "commi": a.commi,
            "aggiornamenti": a.aggiornamenti,
        }
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        (d / f"{a.numero}.json").write_text(blob, encoding="utf-8")
        tot += len(blob.encode("utf-8"))
    return tot


def main() -> int:
    ap = argparse.ArgumentParser(description="Costruisce gli artefatti dati di Panther")
    ap.add_argument("--out", type=Path, default=Path("dist"))
    ap.add_argument("--cache", type=Path, default=Path(".cache/normattiva"))
    ap.add_argument(
        "--offline",
        action="store_true",
        help="usa gli XML già in --cache senza richiamare l'API",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args.out.mkdir(parents=True, exist_ok=True)

    if args.offline:
        sorgenti = {k: args.cache / f"{k}.xml" for k in ("reati_cp", "cds")}
        mancanti = [str(p) for p in sorgenti.values() if not p.exists()]
        if mancanti:
            log.error("--offline ma mancano: %s", mancanti)
            return 1
    else:
        with NormattivaClient() as cli:
            sorgenti = cli.scarica_codici(args.cache)

    # UTC esplicito: il runner CI e la macchina di sviluppo hanno fusi diversi,
    # e build_date finisce nel manifest confrontato fra le due.
    oggi = datetime.now(UTC).date().isoformat()
    articoli = {
        # Il c.p. è nell'annesso, non strutturato -> parser testuale.
        "reati_cp": annex.parse(str(sorgenti["reati_cp"])),
        # Il CdS ha 266 <articolo> -> parser XML.
        "cds": structured.parse(str(sorgenti["cds"])),
    }

    db = args.out / "panther-core.db"
    con = _connect(db)
    with con:
        _inserisci(con, "reati_cp", articoli["reati_cp"], URN_CP, oggi)
        _inserisci(con, "cds", articoli["cds"], URN_CDS, oggi)
        con.executemany(
            "INSERT INTO meta (chiave, valore) VALUES (?,?)",
            [
                ("build_date", oggi),
                ("fonte", "Normattiva OpenData"),
                ("vigenza", "V"),
                ("articoli_cp", str(len(articoli["reati_cp"]))),
                ("articoli_cds", str(len(articoli["cds"]))),
                ("disclaimer", "Consultazione operativa, non fonte ufficiale."),
            ],
        )
    con.execute("VACUUM")
    con.close()

    testi = {t: _scrivi_testi(args.out, t, a) for t, a in articoli.items()}

    manifest = {
        "build_date": oggi,
        "core_db_bytes": db.stat().st_size,
        "core_db_sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
        "testi_bytes": testi,
        "articoli": {t: len(a) for t, a in articoli.items()},
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info("panther-core.db: %.2f MB", db.stat().st_size / 1024 / 1024)
    log.info("testi on-demand: %.2f MB", sum(testi.values()) / 1024 / 1024)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
