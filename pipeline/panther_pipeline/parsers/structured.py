"""Parser per atti NIR con articolato strutturato.

Si applica al Codice della Strada (D.Lgs. 285/1992): 266 elementi
`<articolo id="N">`, individuabili sull'albero XML senza segmentazione
testuale.

Attenzione però: la struttura è solo *parzialmente* semantica. Il markup reale
è così —

    <articolo id="173">
      <num>Art. 173.</num>
      <comma id="art173-com1">
        <num>1</num>
        <corpo>
          <h:p style="text-align: center;">Art. 173 </h:p>          <- header
          <h:p style="text-align: center;">Uso di lenti ... </h:p>  <- RUBRICA
          <h:p>1. Il titolare di patente ... </h:p>                 <- comma 1
          <h:p>2. E' vietato al conducente ... </h:p>               <- comma 2
        </corpo>
      </comma>
    </articolo>

cioè: non esiste `<rubrica>`, e *tutti* i commi stanno dentro il primo
`<comma>` come `<h:p>` piatti. Gli id `artN-comM` non sono affidabili per la
segmentazione — si numera sul prefisso testuale «N. ».
"""

from __future__ import annotations

import re

from lxml import etree

from .annex import Articolo, normalizza_testo, pulisci_rubrica

NIR_NS = "http://www.normeinrete.it/nir/2.2/"
HTML_NS = "http://www.w3.org/HTML/1998/html4"

RE_NUM = re.compile(
    r"Art\.?\s*(?P<num>\d+)\s*(?P<suffisso>(?:-?\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))*)",
    re.IGNORECASE,
)
# Header ripetuto in cima al corpo: "Art. 173" da solo.
RE_HEADER = re.compile(r"^Art\.?\s*\d+[\w\s-]*\.?$", re.IGNORECASE)
# Inizio di un comma numerato: "1. Il titolare ..."
RE_COMMA = re.compile(r"^\d+\s*[.)]\s")


def _numero_da_articolo(el: etree._Element) -> str:
    num_el = el.find(f"{{{NIR_NS}}}num")
    if num_el is not None:
        m = RE_NUM.search("".join(num_el.itertext()))
        if m:
            suf = re.sub(r"[\s-]+", "", m.group("suffisso") or "").lower()
            return f"{m.group('num')}-{suf}" if suf else m.group("num")
    return (el.get("id") or "").strip()


def _paragrafi(el: etree._Element) -> list[str]:
    out: list[str] = []
    for p in el.iter(f"{{{HTML_NS}}}p"):
        txt = normalizza_testo("".join(p.itertext()))
        if txt:
            out.append(txt)
    return out


def parse(xml_path: str | bytes) -> list[Articolo]:
    """Estrae gli articoli da un atto NIR strutturato."""
    tree = etree.parse(xml_path)

    articoli: list[Articolo] = []
    for el in tree.getroot().iter(f"{{{NIR_NS}}}articolo"):
        numero = _numero_da_articolo(el)
        if not numero:
            continue

        art = Articolo(numero=numero)
        paragrafi = _paragrafi(el)
        i = 0

        # 1. Scarta l'header "Art. N" ripetuto.
        if i < len(paragrafi) and RE_HEADER.match(paragrafi[i]):
            i += 1

        # 2. Il paragrafo successivo è la rubrica, se non è già un comma.
        if i < len(paragrafi) and not RE_COMMA.match(paragrafi[i]):
            art.rubrica = pulisci_rubrica(paragrafi[i])
            i += 1

        # 3. Il resto è corpo normativo. I paragrafi non numerati sono
        #    continuazioni del comma precedente (a capo tipografici).
        for p in paragrafi[i:]:
            if RE_COMMA.match(p) or not art.commi:
                art.commi.append(p)
            else:
                art.commi[-1] = f"{art.commi[-1]} {p}"

        articoli.append(art)

    return articoli
