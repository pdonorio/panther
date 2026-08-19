# Panther

**Toolkit operativo del poliziotto** — PWA offline-first per la consultazione
rapida di Codice Penale, Codice della Strada e procedure operative.

Pensata per l'uso reale: una mano sola, schermo piccolo, spesso senza campo.
Nessun backend, nessuna latenza, nessun costo di esercizio.

> ⚠️ Strumento di consultazione operativa, **non fonte ufficiale**.
> Il testo che fa fede è quello pubblicato in Gazzetta Ufficiale.

---

## Come funziona

Non c'è un'API da interrogare in intervento. Il database viaggia con l'app:

```
Normattiva OpenData  ──(GitHub Actions, notturno)──>  panther-core.db
                                                            │
                                                  GitHub Pages
                                                            │
                                              download una tantum
                                                            ▼
                                       IndexedDB  ──>  SQLite (WASM)
                                                            │
                                                    query FTS5 locali
```

Al primo avvio il client scarica ~0.5 MB di database e lo archivia in
IndexedDB. Dagli avvii successivi rivalida via `ETag`: se nulla è cambiato il
server risponde `304` e l'app parte istantaneamente, anche offline.

Il **testo integrale** non sta nel database: pesa ~2.2 MB ed è il campo meno
consultato durante un intervento. Viene scaricato per singolo articolo da
`/testi/<tabella>/<articolo>.json` e messo in cache dal service worker.

### Perché SQLite WASM ufficiale e non sql.js

Il motore è [`@sqlite.org/sqlite-wasm`](https://www.npmjs.com/package/@sqlite.org/sqlite-wasm),
non `sql.js`, e non è una preferenza: **i binari di sql.js non hanno FTS5.**
`pragma_compile_options` sulla 1.14.2 dà `ENABLE_FTS3` e nient'altro, quindi
`cds_fts` non si apre proprio — *«no such module: fts5»* — e `bm25()` non
esiste. Tutta la ricerca del progetto ci passa. La build ufficiale espone
`ENABLE_FTS5`, `bm25()` e il tokenizer `unicode61 remove_diacritics 2`.

Il DB arriva come byte da IndexedDB e si apre con `sqlite3_deserialize`:
resta in memoria, senza OPFS. Il `.wasm` lo risolve Vite (il pacchetto usa
`new URL('sqlite3.wasm', import.meta.url)`), quindi il nome del file non è
scritto da nessuna parte a mano — e non può sfasarsi come è già successo.

## Struttura

| Cartella | Contenuto |
|---|---|
| `pipeline/` | Python — fetch da Normattiva, parsing NIR, build SQLite |
| `frontend/` | React + Vite PWA, SQLite WASM |
| `infra/` | Terraform per S3 + CloudFront — **non applicato**, vedi Deploy |
| `.github/workflows/` | CI, build dati + deploy su GitHub Pages |
| `docs/` | Verifica delle fonti dati |

## Quickstart

### Pipeline

```bash
cd pipeline
python -m venv .venv && ./.venv/bin/pip install -e '.[dev]'

# scarica da Normattiva e costruisce gli artefatti in ../dist
./.venv/bin/python -m panther_pipeline.build --out ../dist

# ricostruisce senza rete, dagli XML già in .cache/
./.venv/bin/python -m panther_pipeline.build --offline --out ../dist

./.venv/bin/pytest -q
```

Output:

```
dist/panther-core.db          ~0.5 MB   campi operativi + indici FTS5
dist/testi/<tab>/<art>.json   ~2.2 MB   testo integrale, on-demand
dist/manifest.json                      hash e dimensioni, per la cache
```

### Frontend

```bash
cd frontend && npm install && npm run dev
```

## Deploy

Il sito sta su **GitHub Pages**, a `https://pdonorio.github.io/panther/`.
Non serve un account cloud e non c'è niente da provisionare: si abilita Pages
una volta (*Settings → Pages → Source: GitHub Actions*) e da lì in poi
`deploy.yml` fa tutto.

Un solo workflow costruisce dati e frontend insieme, perché Pages pubblica in
modo **atomico**: l'artefatto caricato diventa l'intero sito. Gira su push a
`main`, ogni notte alle 03:17 UTC e a mano. Il giro notturno ripubblica solo
se `core_db_sha256` è cambiato rispetto al `manifest.json` già online.

Il sito è servito da una **sottocartella**, quindi nessun path può essere
assoluto: `base` sta in `frontend/vite.config.ts` e il client passa da
`import.meta.env.BASE_URL`. Con un dominio dedicato tornerebbe `'/'`.

Rispetto a CloudFront si perde il controllo degli header: Pages serve tutto con
`cache-control: max-age=600`, non configurabile. Dopo una build notturna un
client può quindi tenere in cache un DB vecchio per una decina di minuti — su
un riferimento normativo aggiornato una volta al giorno, irrilevante.

La **rivalidazione `ETag`**, da cui dipende l'avvio offline di `db.ts`, invece
regge — verificata sul deploy reale:

```console
$ curl -sI https://pdonorio.github.io/panther/panther-core.db | grep -i etag
etag: "6a85b3a1-84000"
$ curl -s -o /dev/null -w '%{http_code} %{size_download}b\n' \
    -H 'If-None-Match: "6a85b3a1-84000"' \
    https://pdonorio.github.io/panther/panther-core.db
304 0b
```

### Alternativa: AWS

`infra/` contiene il Terraform per S3 privato + CloudFront con OAC e ruolo
OIDC, scritto e mai applicato. Serve se in futuro vuoi un dominio dedicato o
il controllo degli header di cache:

```bash
cd infra
terraform init
terraform apply -var 'github_repo=pdonorio/panther'
```

Gli output vanno poi nelle *Variables* del repo (`AWS_DEPLOY_ROLE_ARN`,
`AWS_REGION`, `S3_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`, `PANTHER_DOMAIN`) e
il workflow di deploy va riportato a due job separati.

## I dati

Fonte: **API OpenData di Normattiva** — `api.normattiva.it/.../bff-opendata/v1`.
Pubblica, senza autenticazione. Contratto e limiti verificati con chiamate
reali: vedi **[`docs/data-sources.md`](docs/data-sources.md)**.

Un solo download copre tutto il fabbisogno: la collezione preconfezionata
*Codici* (`formato=XML`, `formatoRichiesta=V`) è uno ZIP da ~6.9 MB con 40 atti,
fra cui entrambi quelli che ci servono.

⚠️ Il download **restituisce a intermittenza `200` con corpo vuoto**, su
qualunque formato. Il client controlla il magic ZIP e ritenta; il workflow, se
proprio non ce la fa, ripubblica dagli XML dell'ultima build riuscita tenuti in
cache. Dettagli e misure in [`docs/data-sources.md`](docs/data-sources.md).

### Due parser, non uno

I due codici hanno strutture diverse e questa è la complessità centrale della
pipeline:

- **Codice della Strada** (D.Lgs. 285/1992) — 266 `<articolo>` sull'albero XML.
  Attenzione: la rubrica *non* è in un elemento `<rubrica>`, è il primo `<h:p>`
  centrato del corpo, e tutti i commi stanno dentro un unico `<comma>`.
- **Codice Penale** (R.D. 1398/1930) — il file espone solo **3** `<articolo>`,
  che sono quelli del *decreto di approvazione*. Il codice vero è un
  `<annesso>` di ~6800 paragrafi piatti, segmentato sugli header `Art. N.`.

Il testo NIR rende inoltre gli accenti come apostrofo ASCII (`velocita'`):
la normalizzazione li ripristina con una regola sulla vocale finale, senza
toccare le elisioni (`dell'alcool`, `un'auto`).

### Cosa la pipeline non può produrre

Diversi campi dello schema **non esistono in nessuna fonte pubblica**: sono
contenuto redazionale da scrivere a mano —

`sintesi_operativa`, `note_operatore`, `pene`, `aggravanti`, `procedibilita`,
`importo_sanzione`, `pagamento_ridotto`, `pagamento_oltre_60_giorni`,
`testo_verbale`, e l'intera tabella `interventi_minori`.

Vivono in un overlay versionato a parte (`pipeline/editorial/`) così il sync
notturno non li sovrascrive. Finché non sono redatti, la ricerca per concetto
resta limitata: la FTS indicizza `articolo`, `titolo`, `sintesi_operativa`,
quindi cercare *"ebbrezza"* non trova l'art. 186 (la cui rubrica dice
"Guida sotto l'influenza dell'alcool").

⚠️ **Importi del CdS**: quelli nel testo degli articoli non sono aggiornati.
L'art. 195 c.d.s. impone la rivalutazione ISTAT biennale, che il testo non
riflette. Il campo `importi_aggiornati_al` è obbligatorio in UI.

## Stato

| Componente | Stato |
|---|---|
| Client API Normattiva | ✅ funzionante, verificato su dati reali |
| Parser CP / CdS | ✅ 945 e 266 articoli, 25 test verdi |
| Build SQLite + FTS5 | ✅ 0.5 MB core + 2.2 MB testi |
| Workflow CI / deploy | ✅ verdi sul deploy reale |
| GitHub Pages | ✅ online, ETag verificato (`304`) |
| Terraform (AWS) | 💤 scritto, mai applicato — alternativa, non serve ora |
| Frontend | 🚧 scheletro: caricamento DB e ricerca ci sono, manca la UI vera |
| Contenuto editoriale | ❌ da iniziare |
| Licenza dei dati | ❓ **da chiarire** (vedi sotto) |

## Licenza

Il **codice** di questo repository è rilasciato sotto licenza MIT
(vedi [`LICENSE`](LICENSE)).

I **dati** provengono da Normattiva e ricadono sotto la licenza del portale.
Il portale referenzia sia CC BY 4.0 sia CC BY-NC 4.0 senza che sia stato
possibile stabilire quale copra la collezione *Codici*: **va accertato prima di
redistribuire `panther-core.db`**. Se fosse BY-NC, la restrizione è
probabilmente ininfluente per uno strumento gratuito, ma va verificata.
