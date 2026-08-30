-- Panther — schema SQLite (target: @sqlite.org/sqlite-wasm nel browser)
-- Il DB è READ-ONLY lato client: nessun trigger di scrittura utente.
--
-- Non esistono migrazioni incrementali: il DB è un artefatto deterministico,
-- ricostruito da zero a ogni build (build.py::_connect fa unlink prima di
-- creare). Cambiare questo file È la migrazione. Quello che va gestito è il
-- client, che tiene una copia in IndexedDB: vedi meta.schema_version.

PRAGMA journal_mode = DELETE;   -- WAL non ha senso per un artefatto statico
PRAGMA page_size    = 4096;

-- Metadati di build: la UI DEVE mostrare vigenza e data di accesso.
CREATE TABLE IF NOT EXISTS meta (
    chiave TEXT PRIMARY KEY,
    valore TEXT NOT NULL
);

-- ---------------------------------------------------------------- Codice Penale
CREATE TABLE IF NOT EXISTS reati_cp (
    id                  INTEGER PRIMARY KEY,
    articolo            TEXT NOT NULL,          -- "61-bis"
    titolo              TEXT NOT NULL DEFAULT '',
    sintesi_operativa   TEXT NOT NULL DEFAULT '',   -- editoriale
    pene                TEXT NOT NULL DEFAULT '',   -- editoriale
    aggravanti          TEXT NOT NULL DEFAULT '',   -- editoriale
    procedibilita       TEXT NOT NULL DEFAULT '',   -- editoriale
    note_operatore      TEXT NOT NULL DEFAULT '',   -- editoriale
    testo_integrale     TEXT,                   -- NULL in panther-core.db (vedi split)
    testo_integrale_url TEXT NOT NULL DEFAULT '',
    legge_numero        TEXT NOT NULL DEFAULT '1398',
    legge_anno          INTEGER NOT NULL DEFAULT 1930,
    fonte               TEXT NOT NULL DEFAULT 'Normattiva OpenData',
    data_accesso        TEXT NOT NULL,
    urn                 TEXT NOT NULL DEFAULT '',
    vigenza_data        TEXT NOT NULL DEFAULT '',
    hash_fonte          TEXT NOT NULL DEFAULT '',
    UNIQUE (articolo)
);

-- ------------------------------------------------------------ Codice della Strada
CREATE TABLE IF NOT EXISTS cds (
    id                        INTEGER PRIMARY KEY,
    articolo                  TEXT NOT NULL,
    titolo                    TEXT NOT NULL DEFAULT '',
    sintesi_operativa         TEXT NOT NULL DEFAULT '',   -- editoriale
    importo_sanzione          TEXT NOT NULL DEFAULT '',   -- editoriale
    pagamento_ridotto         TEXT NOT NULL DEFAULT '',   -- editoriale
    pagamento_oltre_60_giorni TEXT NOT NULL DEFAULT '',   -- editoriale
    note_operatore            TEXT NOT NULL DEFAULT '',   -- editoriale
    testo_verbale             TEXT NOT NULL DEFAULT '',   -- editoriale
    testo_integrale           TEXT,
    testo_integrale_url       TEXT NOT NULL DEFAULT '',
    legge_numero              TEXT NOT NULL DEFAULT '285',
    legge_anno                INTEGER NOT NULL DEFAULT 1992,
    fonte                     TEXT NOT NULL DEFAULT 'Normattiva OpenData',
    data_accesso              TEXT NOT NULL,
    urn                       TEXT NOT NULL DEFAULT '',
    vigenza_data              TEXT NOT NULL DEFAULT '',
    hash_fonte                TEXT NOT NULL DEFAULT '',
    -- Art. 195 c.d.s.: rivalutazione ISTAT biennale degli importi.
    -- Il testo dell'articolo NON la riflette: la UI deve esporre questa data.
    importi_aggiornati_al     TEXT NOT NULL DEFAULT '',
    UNIQUE (articolo)
);

-- ====================================================== Interventi operativi
-- Ex `interventi_minori`. Il nome vecchio era ambiguo fra «interventi di
-- piccola entità» e «interventi che riguardano i minorenni», e non era
-- nessuno dei due: qui stanno gli interventi tipici di una volante, la Top 20.
-- I minorenni compaiono due volte e vanno tenute distinte:
--   - come intervento a sé (minore in pericolo / autore di reato);
--   - come verifica trasversale che quasi ogni altra scheda deve fare,
--     ed è il flag `coinvolge_minori`.
--
-- L'ingresso al prodotto si ribalta: l'operatore non cerca un articolo, parte
-- dalla situazione ("sono intervenuto per una lite") e la scheda lo accompagna.
CREATE TABLE IF NOT EXISTS interventi (
    id            INTEGER PRIMARY KEY,
    -- Chiave stabile e leggibile: è il nome del file editoriale e regge i
    -- riferimenti incrociati. Gli id numerici cambiano a ogni rebuild.
    slug          TEXT NOT NULL,          -- "lite-aggressione"
    posizione     INTEGER NOT NULL DEFAULT 0,   -- ordine nella Top 20
    titolo        TEXT NOT NULL,
    categoria     TEXT NOT NULL DEFAULT '',     -- pg | stradale | particolari
    -- Semaforo operativo: permette di non leggere tutta la scheda.
    urgenza       TEXT NOT NULL DEFAULT 'ordinario'
                  CHECK (urgenza IN ('ordinario', 'attenzione', 'urgente')),
    -- Verifica trasversale, non una categoria: una lite o una violenza
    -- domestica con un minore presente cambia gli obblighi.
    coinvolge_minori INTEGER NOT NULL DEFAULT 0 CHECK (coinvolge_minori IN (0, 1)),
    tag           TEXT NOT NULL DEFAULT '[]',   -- JSON array

    -- Le sezioni della scheda, nell'ordine in cui si leggono sul posto.
    descrizione              TEXT NOT NULL DEFAULT '',
    procedura_operativa      TEXT NOT NULL DEFAULT '',   -- COSA FARE
    accertamenti_fondamentali TEXT NOT NULL DEFAULT '',  -- COSA VERIFICARE SUBITO
    procedibilita            TEXT NOT NULL DEFAULT '',   -- d'ufficio / a querela, e perché
    poteri_operativi         TEXT NOT NULL DEFAULT '',   -- arresto, perquisizione, sequestro
    consigli_operativi       TEXT NOT NULL DEFAULT '',   -- cosa conviene fare
    errori_ricorrenti        TEXT NOT NULL DEFAULT '',   -- cosa va storto di solito
    casi_particolari         TEXT NOT NULL DEFAULT '',
    atti_da_redigere         TEXT NOT NULL DEFAULT '[]', -- JSON array, è una checklist

    -- Tracciabilità del contenuto editoriale: chi l'ha scritto e quando.
    -- Serve a sapere se una scheda è stata verificata da un operatore vero.
    autore        TEXT NOT NULL DEFAULT '',
    verificata_il TEXT NOT NULL DEFAULT '',
    UNIQUE (slug)
);

-- Riferimenti normativi di una scheda.
--
-- Era un JSON array di stringhe dentro la scheda: andava bene per stamparlo,
-- non per interrogarlo. Serve una relazione vera per due motivi:
--   1. un intervento reale tocca più reati insieme (una violenza domestica
--      coinvolge maltrattamenti, lesioni, minaccia, danneggiamento, minori);
--   2. senza relazione non si può rispondere a «quali schede toccano l'art.
--      572?», che è esattamente la domanda del controllo di obsolescenza.
--
-- ATTENZIONE alla colonna `tabella`: buona parte della Top 20 cita fonti che
-- Panther NON ha in archivio — c.p.p., D.P.R. 309/1990, L. 110/1975, TULPS,
-- D.Lgs. 286/1998, D.P.R. 448/1988. Quelle citazioni vanno comunque mostrate,
-- quindi `tabella`/`articolo` sono NULL e resta solo `citazione` + `urn`.
-- Il controllo di obsolescenza copre solo i riferimenti risolti.
CREATE TABLE IF NOT EXISTS interventi_articoli (
    id            INTEGER PRIMARY KEY,
    intervento_id INTEGER NOT NULL REFERENCES interventi(id),
    -- Riferimento risolto a un articolo che abbiamo davvero. NULL se la fonte
    -- non è in archivio.
    tabella       TEXT CHECK (tabella IN ('reati_cp', 'cds')),
    articolo      TEXT,
    -- Come va mostrato all'operatore: sempre valorizzato, anche non risolto.
    citazione     TEXT NOT NULL,                -- "art. 380 c.p.p."
    fonte         TEXT NOT NULL DEFAULT '',     -- "c.p.p." | "D.P.R. 309/1990"
    urn           TEXT NOT NULL DEFAULT '',     -- permalink Normattiva, se noto
    ruolo         TEXT NOT NULL DEFAULT 'principale'
                  CHECK (ruolo IN ('principale', 'aggravante', 'concorrente', 'procedurale')),
    -- Obsolescenza silenziosa: il testo di legge si aggiorna ogni notte da
    -- Normattiva, la scheda scritta a mano no. Qui si congela l'hash che
    -- l'articolo aveva quando la scheda è stata redatta; la build confronta e
    -- segnala le schede da rileggere. Senza questo, una scheda continua a
    -- sembrare giusta dopo che la norma sotto è cambiata — lo stesso difetto
    -- degli importi non rivalutati, generalizzato.
    hash_al_momento TEXT NOT NULL DEFAULT '',
    UNIQUE (intervento_id, citazione)
);

CREATE INDEX IF NOT EXISTS idx_interventi_articoli_intervento
    ON interventi_articoli (intervento_id);
-- Il verso che serve al controllo di obsolescenza: dall'articolo alle schede.
CREATE INDEX IF NOT EXISTS idx_interventi_articoli_articolo
    ON interventi_articoli (tabella, articolo);

-- ------------------------------------------------------------------ Modulistica
-- I PDF non stanno nel DB: viaggiano come file sotto dist/modulistica/ e li
-- prende il service worker on-demand, come i testi integrali. Qui c'è solo
-- l'indice, che è ciò su cui si cerca e si filtra.
--
-- `provenienza` non è burocrazia: la modulistica operativa dipende dagli
-- uffici e dalle Questure, quindi un modello va sempre accompagnato da dove
-- viene. Serve all'operatore e servirà al catalogo del riuso.
CREATE TABLE IF NOT EXISTS modulistica (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL,
    titolo       TEXT NOT NULL,
    categoria    TEXT NOT NULL DEFAULT '',
    file         TEXT NOT NULL,                -- "modulistica/verbale-identificazione.pdf"
    bytes        INTEGER NOT NULL DEFAULT 0,
    sha256       TEXT NOT NULL DEFAULT '',
    provenienza  TEXT NOT NULL DEFAULT '',     -- ufficio/Questura di origine
    aggiornato_al TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    UNIQUE (slug)
);

-- La modulistica è sia una sezione a sé sia un filtro dentro una scheda.
CREATE TABLE IF NOT EXISTS interventi_modulistica (
    intervento_id  INTEGER NOT NULL REFERENCES interventi(id),
    modulistica_id INTEGER NOT NULL REFERENCES modulistica(id),
    obbligatorio   INTEGER NOT NULL DEFAULT 0 CHECK (obbligatorio IN (0, 1)),
    ordine         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (intervento_id, modulistica_id)
);

-- --------------------------------------------------------------- Full-Text Search
-- `unicode61 remove_diacritics 2` così "puo" trova "può": in intervento
-- nessuno digita gli accenti.
CREATE VIRTUAL TABLE IF NOT EXISTS reati_cp_fts USING fts5(
    articolo, titolo, sintesi_operativa,
    content='reati_cp', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);

CREATE VIRTUAL TABLE IF NOT EXISTS cds_fts USING fts5(
    articolo, titolo, sintesi_operativa,
    content='cds', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);

-- La ricerca sugli interventi è quella che risolve il problema vero: chi cerca
-- "ebbrezza" non trova l'art. 186 (la rubrica dice "Guida sotto l'influenza
-- dell'alcool"), ma trova la scheda che si chiama così.
CREATE VIRTUAL TABLE IF NOT EXISTS interventi_fts USING fts5(
    titolo, categoria, descrizione, procedura_operativa,
    content='interventi', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);

CREATE VIRTUAL TABLE IF NOT EXISTS modulistica_fts USING fts5(
    titolo, categoria,
    content='modulistica', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
