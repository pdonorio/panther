# Fonti dati — verifica tecnica

Verificato il 2026-08-18 con chiamate live. Questo documento registra **cosa è
stato testato**, non cosa si presume.

## 1. Esiste una API pubblica Normattiva

Sì. Il portale `dati.normattiva.it` è una SPA Angular il cui `assets/env.js`
dichiara il base URL:

```
https://api.normattiva.it/t/normattiva.api/bff-opendata/v1
```

Documentazione pubblicata dal portale stesso:

| Risorsa | URL |
|---|---|
| OpenAPI 3 | `https://dati.normattiva.it/assets/come_fare_per/openapi-bff-opendata.json` |
| Postman collection | `https://dati.normattiva.it/assets/come_fare_per/openapi-bff-opendata.postman_collection.json` |
| Manuale API (PDF) | `https://dati.normattiva.it/assets/come_fare_per/API_Normattiva_OpenData.pdf` |
| Akoma Ntoso (PDF) | `https://dati.normattiva.it/assets/come_fare_per/Portale_Normattiva_2.0-Strutturazione_degli_atti_in_Akoma_Ntoso_26-07-2021.pdf` |

**Autenticazione: nessuna.** `components.securitySchemes` è vuoto e la
`security` globale è `null`. Chiamate GET anonime rispondono `200`.
Non sono documentati rate limit — la pipeline applica comunque backoff.

> Nota: lo `servers` block dell'OpenAPI dichiara `http://localhost:9090/bff-opendata`
> (artefatto di generazione). Il base URL reale è quello in `env.js`.

## 2. Endpoint rilevanti

```
POST /api/v1/ricerca/semplice              ricerca full-text
POST /api/v1/ricerca/avanzata              ricerca per estremi
POST /api/v1/ricerca/aggiornati            atti aggiornati fra due date  ← sync incrementale
POST /api/v1/atto/dettaglio-atto-urn       dettaglio atto per URN-NIR
GET  /api/v1/collections/collection-predefinite            elenco collezioni
GET  /api/v1/collections/download/collection-preconfezionata  download bulk  ← import iniziale
GET  /api/v1/tipologiche/estensioni        formati export disponibili
```

Ricerca asincrona per estrazioni grandi:
`nuova-ricerca` → `conferma-ricerca` → `check-status/{token}` → `download/collection-asincrona/{token}`.

### Parametri di `collection-preconfezionata` (attenzione)

I nomi sono controintuitivi e li abbiamo sbagliati al primo tentativo:

- `nome` — nome collezione, es. `Codici`
- `formato` — **formato file**: `XML`, `AKN`, `JSON`, `PDF`, `EPUB`, `RTF`, `HTML`, `URI`
- `formatoRichiesta` — **vigenza**: `O` (originale), `M` (multivigente), `V` (vigente)

Invertirli restituisce `400 {"code":"1006","message":"Formato vigenza non consentito (valori consentiti O,M,V)"}`.

L'endpoint risponde `302` verso un URL firmato monouso su
`/t/normattiva.api/file-download/v1/download/<token>`: **serve `curl -L`** /
`follow_redirects=True`.

### Il download restituisce a intermittenza un corpo vuoto

Verificato il 2026-08-19: lo stesso URL risponde `200 application/octet-stream`
con `Transfer-Encoding: chunked` e **0 byte**, per poi funzionare pochi minuti
dopo. Non dipende dal formato — nel giro di due minuti:

| | primo giro | secondo giro |
|---|---|---|
| `formato=XML` | **0 byte** | 6 918 447 byte |
| `formato=AKN` | 10 531 559 byte | **0 byte** |
| `formato=JSON` | — | 8 992 819 byte |

Gli endpoint di lettura (`collection-predefinite`) restavano sani nel
frattempo, quindi non è un'indisponibilità generale del servizio: sembra una
race fra l'emissione del token firmato e la materializzazione del file.

Conseguenza pratica: **`200` non basta come criterio di successo.** Il client
controlla il magic ZIP (`PK\x03\x04`) e tratta il corpo vuoto come errore
ritentabile — senza, il file vuoto arriva fino a `zipfile` e muore con un
`BadZipFile` che non dice niente. Con 6 tentativi e backoff esponenziale non
si è più visto fallire il giro completo.

## 3. La collezione «Codici» copre entrambi i codici

`GET /collections/collection-predefinite` elenca `Codici` — 40 atti, rigenerata
quotidianamente (`dataCreazione` cambia ogni giorno).

Download verificato: `nome=Codici&formato=XML&formatoRichiesta=V` → ZIP **6.9 MB**,
40 file XML. Contiene:

| Atto | Directory nello ZIP |
|---|---|
| Codice Penale — R.D. 1398/1930 | `REGIO DECRETO_19301019_1398/` |
| Codice della Strada — D.Lgs. 285/1992 | `DECRETO LEGISLATIVO_19920430_285/` |

Un solo download da 6.9 MB copre l'intero fabbisogno dati del progetto. Non
serve scraping.

## 4. Il formato NIR richiede DUE parser distinti

Gli XML sono **NIR** (`http://www.normeinrete.it/nir/2.2/`), non Akoma Ntoso —
AKN è disponibile come formato alternativo (`formato=AKN`) e andrà valutato.

Questa è la scoperta che condiziona la pipeline: **i due codici non hanno la
stessa struttura.**

### Codice della Strada — strutturato ✅

266 elementi `<articolo id="N">`, ciascuno con `<comma>` / `<corpo>`.
Parsing diretto sull'albero XML.

### Codice Penale — NON strutturato ⚠️

Il file contiene solo **3** `<articolo>` — sono gli articoli del *regio decreto
di approvazione*, non del codice. Il testo del codice vive dentro `<annesso>`
come ~6800 `<h:p>` piatti:

```
|Codice Penale|CODICE PENALE |Art. 1. |(Reati e pene: disposizione espressa di legge) |Nessuno puo' essere punito ...
```

Serve un parser testuale che segmenti sugli header `Art. N.` e tratti la riga
successiva fra parentesi come rubrica. È il pattern generale dei codici
pre-repubblicani approvati per decreto (anche c.c., c.p.p. sono così).

Complicazione: il testo contiene blocchi `AGGIORNAMENTO (n)` inline con la
cronologia delle modifiche e note della Corte Costituzionale. Vanno separati dal
corpo normativo, non concatenati.

Il testo usa apostrofi ASCII al posto degli accenti (`puo'`, `ne'`) — da
normalizzare per la ricerca FTS.

## 5. Licenza — DA CHIARIRE prima della pubblicazione ⚠️

La pagina *Dati disponibili* referenzia **due** licenze:
`CC BY 4.0` e `CC BY-NC 4.0`. Il markup è minificato in un bundle Angular e non
è stato possibile stabilire con certezza quale si applichi a quale dataset.

Ha impatto diretto: se la collezione «Codici» è **BY-NC**, `panther.db` non può
essere redistribuito in un contesto commerciale. Per un tool gratuito per
operatori di polizia la restrizione è probabilmente ininfluente, ma va accertata
leggendo la pagina resa nel browser prima di pubblicare il database.

Da verificare anche `https://dati.normattiva.it/note-legali`.

## 6. Cosa NON viene dalle fonti pubbliche

Questi campi dello schema non esistono in nessun dataset — sono contenuto
editoriale da produrre:

`sintesi_operativa`, `note_operatore`, `pene` (normalizzato), `aggravanti`,
`procedibilita`, `importo_sanzione`, `pagamento_ridotto`,
`pagamento_oltre_60_giorni`, `testo_verbale`, e l'intera tabella
`interventi_minori`.

Gli importi del CdS sono nel testo degli articoli ma vanno estratti e soprattutto
**rivalutati**: l'art. 195 c.d.s. prevede l'aggiornamento ISTAT biennale degli
importi, che il testo dell'articolo non riflette.

Vedi `docs/editorial.md` (TODO) per il modello di curation.
