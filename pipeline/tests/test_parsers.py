"""Test dei parser NIR.

I test che toccano gli XML reali si auto-skippano se la cache è vuota, così la
suite gira anche senza rete. Per popolarla:

    python -m panther_pipeline.build --out dist
"""

from __future__ import annotations

from pathlib import Path

import pytest

from panther_pipeline.parsers import annex, structured
from panther_pipeline.parsers.annex import normalizza_testo, pulisci_rubrica

CACHE = Path(__file__).resolve().parents[1] / ".cache" / "normattiva"
CP_XML = CACHE / "reati_cp.xml"
CDS_XML = CACHE / "cds.xml"

richiede_cache = pytest.mark.skipif(
    not (CP_XML.exists() and CDS_XML.exists()),
    reason="cache XML assente: esegui prima `python -m panther_pipeline.build`",
)


# --- normalizzazione ---------------------------------------------------------

@pytest.mark.parametrize(
    ("grezzo", "atteso"),
    [
        ("Limiti di velocita'", "Limiti di velocità"),
        ("Chiunque puo' essere", "Chiunque può essere"),
        ("la citta' e la societa'", "la città e la società"),
        ("piu' grave", "più grave"),
        ("cosi'", "così"),
        ("E' vietato", "È vietato"),
        # "e" tronca acuta vs grave
        ("ne' con pene", "né con pene"),
        ("perche' non", "perché non"),
        ("e' punito", "è punito"),
    ],
)
def test_accenti_tronchi(grezzo: str, atteso: str) -> None:
    assert normalizza_testo(grezzo) == atteso


@pytest.mark.parametrize(
    "elisione",
    ["dell'alcool", "un'autovettura", "l'obbligo", "nell'esercizio", "all'articolo"],
)
def test_elisioni_intatte(elisione: str) -> None:
    """L'apostrofo di elisione NON è un accento: non va toccato."""
    assert normalizza_testo(elisione) == elisione


@pytest.mark.parametrize(
    ("grezzo", "atteso"),
    [
        ("( (Circostanza aggravante del reato transnazionale).)", "Circostanza aggravante del reato transnazionale"),
        ("(Omicidio)", "Omicidio"),
        ("( (Istigazione). )", "Istigazione"),
        ("Furto", "Furto"),
    ],
)
def test_pulisci_rubrica(grezzo: str, atteso: str) -> None:
    assert pulisci_rubrica(grezzo) == atteso


# --- Codice Penale (parser annesso) -----------------------------------------

@richiede_cache
def test_cp_articoli_noti() -> None:
    per_numero = {a.numero: a for a in annex.parse(str(CP_XML))}

    assert per_numero["575"].rubrica == "Omicidio"
    assert per_numero["624"].rubrica == "Furto"
    assert per_numero["628"].rubrica == "Rapina"
    # Articolo inserito da legge successiva: doppie parentesi da ripulire.
    assert per_numero["61-bis"].rubrica == "Circostanza aggravante del reato transnazionale"
    # Accenti ripristinati nel corpo.
    assert "è punito" in per_numero["575"].testo_integrale


@richiede_cache
def test_cp_copertura() -> None:
    articoli = annex.parse(str(CP_XML))
    numeri = [int(a.numero.split("-")[0]) for a in articoli]
    assert min(numeri) == 1
    # Il c.p. si chiude all'art. 734(-bis): se il massimo cambia, il parser sta
    # raccogliendo "Art. N" spurî dai blocchi AGGIORNAMENTO.
    assert max(numeri) == 734
    assert len(articoli) > 700


@richiede_cache
def test_cp_aggiornamenti_separati() -> None:
    """I blocchi AGGIORNAMENTO non devono finire nel corpo normativo."""
    per_numero = {a.numero: a for a in annex.parse(str(CP_XML))}
    art2 = per_numero["2"]
    assert art2.aggiornamenti, "art. 2 ha modifiche note, devono essere estratte"
    assert "AGGIORNAMENTO" not in art2.testo_integrale


# --- Codice della Strada (parser strutturato) -------------------------------

@richiede_cache
def test_cds_conta_articoli() -> None:
    assert len(structured.parse(str(CDS_XML))) == 266


@richiede_cache
def test_cds_rubriche() -> None:
    per_numero = {a.numero: a for a in structured.parse(str(CDS_XML))}
    assert per_numero["186"].rubrica == "Guida sotto l'influenza dell'alcool"
    assert per_numero["142"].rubrica == "Limiti di velocità"
    assert per_numero["173"].rubrica == "Uso di lenti o di determinati apparecchi durante la guida"


@richiede_cache
def test_cds_nessuna_rubrica_vuota() -> None:
    """Regressione: le rubriche del CdS non stanno in <rubrica> ma nel primo
    <h:p> centrato del corpo. Sbagliando la lettura, uscivano tutte vuote."""
    vuote = [a.numero for a in structured.parse(str(CDS_XML)) if not a.rubrica]
    assert vuote == []


@richiede_cache
def test_cds_commi_segmentati() -> None:
    """Tutti i commi stanno in un solo <comma>: la segmentazione è testuale."""
    per_numero = {a.numero: a for a in structured.parse(str(CDS_XML))}
    art173 = per_numero["173"]
    assert len(art173.commi) >= 2
    assert art173.commi[0].startswith("1.")
    # L'header "Art. 173" ripetuto non deve finire nel corpo.
    assert not art173.commi[0].startswith("Art.")
