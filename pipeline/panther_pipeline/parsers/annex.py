"""Parser per codici il cui testo vive dentro <annesso> come <h:p> piatti.

Si applica al Codice Penale (R.D. 1398/1930) e in generale ai codici
pre-repubblicani approvati per decreto: il file NIR espone solo gli articoli
del *decreto di approvazione* (3, nel caso del c.p.), mentre il codice vero è
un annesso non strutturato di ~6800 paragrafi.

La segmentazione avviene sugli header testuali `Art. N.`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from lxml import etree

NIR_NS = "http://www.normeinrete.it/nir/2.2/"
HTML_NS = "http://www.w3.org/HTML/1998/html4"

# "Art. 1." / "Art. 61-bis." / "Art.  240 bis"
RE_ARTICOLO = re.compile(
    r"^Art\.?\s*(?P<num>\d+)\s*(?P<suffisso>(?:-?\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))*)\s*\.?\s*$",
    re.IGNORECASE,
)
# La rubrica è la riga immediatamente successiva, fra parentesi tonde.
RE_RUBRICA = re.compile(r"^\((?P<t>.+)\)\.?$", re.DOTALL)
# Blocchi di cronologia modifiche da separare dal corpo normativo.
RE_AGGIORNAMENTO = re.compile(r"^-{3,}\s*$|^AGGIORNAMENTO\s*\(\d+\)", re.IGNORECASE)

# --- normalizzazione accenti -------------------------------------------------
# Il testo NIR rende gli accenti come apostrofo ASCII: "velocita'" -> "velocità".
# Non è un elenco di parole: è una regola generale sulla vocale finale, perché
# qualunque lista si rivelerebbe incompleta (il c.p. + il CdS hanno centinaia di
# parole tronche distinte).
#
# La regola scatta SOLO a fine parola, cioè quando l'apostrofo non è seguito da
# una lettera. Così "velocita'." viene convertito ma le elisioni no:
# "dell'alcool", "un'autovettura", "l'obbligo" restano intatte.
_VOCALI_GRAVI = {"a": "à", "i": "ì", "o": "ò", "u": "ù"}

# La "e" tronca è ambigua: "e'" (verbo) vuole È GRAVE, ma "perche'/ne'/poiche'"
# vogliono É ACUTA. Si enumerano solo le acute, il resto ricade su "è".
_E_ACUTA = {
    "che", "perche", "poiche", "affinche", "giacche", "benche", "cosicche",
    "finche", "nonche", "sicche", "anziche", "ne", "se",
}
_RE_TRONCA = re.compile(r"\b(\w*?)([aeiou])'(?![\w'])", re.IGNORECASE | re.UNICODE)

# Tronche in cui l'apostrofo NON è un accento reso in ASCII e va lasciato dov'è.
# "po'" (troncamento di «poco») è l'unico che ricorre davvero nel testo di
# legge, e senza questa eccezione diventa "pò", che è un errore di ortografia.
# Gli imperativi tronchi sono rari in un codice ma seguono la stessa regola:
# "fà", "và", "stà" non esistono, quindi l'eccezione non può togliere nulla.
# Restano fuori di proposito due casi in cui l'apostrofo È un accento:
#   "da'" -> «dà», che nel testo NIR è la terza persona di dare, non l'imperativo;
#   "di'" -> «dì», che in un testo del 1930 vuol dire «giorno» molto più spesso
#            di quanto sia l'imperativo di dire.
_APOSTROFO_RESTA = {"po", "fa", "va", "sta"}

# Spazi da compattare: include NBSP (U+00A0), usato a piene mani nel testo NIR.
_RE_SPAZI = re.compile("[ \t\u00a0\u2007\u202f]+")


def _accenta(m: re.Match[str]) -> str:
    testa, vocale = m.group(1), m.group(2)
    if (testa + vocale).lower() in _APOSTROFO_RESTA:
        return m.group(0)
    bassa = vocale.lower()
    if bassa == "e":
        parola = (testa + vocale).lower()
        accentata = "é" if parola in _E_ACUTA else "è"
    else:
        accentata = _VOCALI_GRAVI[bassa]
    if vocale.isupper():
        accentata = accentata.upper()
    return testa + accentata


def normalizza_testo(s: str) -> str:
    """Compatta spazi e ripristina gli accenti resi come apostrofo ASCII."""

    s = _RE_TRONCA.sub(_accenta, s)
    s = unicodedata.normalize("NFC", s)
    return _RE_SPAZI.sub(" ", s).strip()


def pulisci_rubrica(s: str) -> str:
    """Rimuove le parentesi ridondanti dalle rubriche.

    Gli articoli inseriti da leggi successive arrivano marcati con doppie
    tonde — «( (Circostanza aggravante del reato transnazionale).)» — perché
    nel testo NIR la doppia parentesi segnala l'inserimento. Non è rubrica.
    """
    s = normalizza_testo(s)
    prev = None
    while prev != s:
        prev = s
        s = s.strip().strip(".").strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()
    return s


@dataclass
class Articolo:
    numero: str                      # "1", "61-bis"
    rubrica: str = ""                # testo fra parentesi
    commi: list[str] = field(default_factory=list)
    aggiornamenti: list[str] = field(default_factory=list)

    @property
    def testo_integrale(self) -> str:
        return "\n".join(self.commi)


def _paragrafi_annesso(root: etree._Element) -> list[str]:
    """Tutti gli <h:p> contenuti negli <annesso>, come testo piatto."""
    out: list[str] = []
    for annesso in root.iter(f"{{{NIR_NS}}}annesso"):
        for p in annesso.iter(f"{{{HTML_NS}}}p"):
            txt = normalizza_testo("".join(p.itertext()))
            if txt:
                out.append(txt)
    return out


def _numero(m: re.Match[str]) -> str:
    suf = re.sub(r"[\s-]+", "", m.group("suffisso") or "").lower()
    return f"{m.group('num')}-{suf}" if suf else m.group("num")


def parse(xml_path: str | bytes) -> list[Articolo]:
    """Estrae gli articoli dall'annesso di un file NIR non strutturato."""
    tree = etree.parse(xml_path)
    paragrafi = _paragrafi_annesso(tree.getroot())

    articoli: list[Articolo] = []
    corrente: Articolo | None = None
    in_aggiornamento = False
    attende_rubrica = False

    for p in paragrafi:
        m = RE_ARTICOLO.match(p)
        if m:
            corrente = Articolo(numero=_numero(m))
            articoli.append(corrente)
            in_aggiornamento = False
            attende_rubrica = True
            continue

        if corrente is None:
            continue  # intestazione della raccolta, prima di Art. 1

        if RE_AGGIORNAMENTO.match(p):
            in_aggiornamento = True
            attende_rubrica = False
            if not p.startswith("---"):
                corrente.aggiornamenti.append(p)
            continue

        if in_aggiornamento:
            corrente.aggiornamenti.append(p)
            continue

        if attende_rubrica:
            attende_rubrica = False
            r = RE_RUBRICA.match(p)
            if r:
                corrente.rubrica = pulisci_rubrica(r.group("t"))
                continue
            # Alcuni articoli non hanno rubrica: il paragrafo è già corpo.

        corrente.commi.append(p)

    return articoli
