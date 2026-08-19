-- Panther — schema SQLite (target: sql.js / wa-sqlite in browser)
-- Il DB è READ-ONLY lato client: nessun trigger di scrittura utente.

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

-- ------------------------------------------------------------ Procedure operative
CREATE TABLE IF NOT EXISTS interventi_minori (
    id                       INTEGER PRIMARY KEY,
    titolo                   TEXT NOT NULL,
    categoria                TEXT NOT NULL DEFAULT '',
    tag                      TEXT NOT NULL DEFAULT '[]',   -- JSON array
    descrizione              TEXT NOT NULL DEFAULT '',
    procedura_operativa      TEXT NOT NULL DEFAULT '',
    accertamenti_fondamentali TEXT NOT NULL DEFAULT '',
    errori_ricorrenti        TEXT NOT NULL DEFAULT '',
    riferimenti_normativi    TEXT NOT NULL DEFAULT '[]',   -- JSON array
    atti_da_redigere         TEXT NOT NULL DEFAULT '[]'    -- JSON array
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

CREATE VIRTUAL TABLE IF NOT EXISTS interventi_minori_fts USING fts5(
    titolo, categoria, descrizione,
    content='interventi_minori', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
