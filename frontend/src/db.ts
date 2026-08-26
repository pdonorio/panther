/**
 * Caricamento e query del database Panther lato client.
 *
 * Strategia (vedi boot_up.yaml -> delivery.split):
 *   1. `panther-core.db` (~0.5MB) scaricato una volta e tenuto in IndexedDB.
 *   2. Rivalidazione via ETag a ogni avvio: se il server risponde 304 si usa
 *      la copia locale, quindi a regime l'avvio è offline e istantaneo.
 *   3. Il testo integrale NON è nel DB: si prende on-demand da /testi/.
 */

// Build WASM ufficiale di SQLite, non sql.js: quest'ultimo è compilato con
// ENABLE_FTS3 e basta (verificato su pragma_compile_options, v1.14.2), quindi
// `cds_fts` non si apre nemmeno — "no such module: fts5". Qui invece FTS5,
// bm25() e `remove_diacritics 2` ci sono. Il .wasm lo risolve Vite da solo:
// il pacchetto usa `new URL('sqlite3.wasm', import.meta.url)`, che in build
// diventa un asset con l'hash nel nome e l'URL già completo di base.
import sqlite3InitModule, { type Database, type Sqlite3Static } from '@sqlite.org/sqlite-wasm'

// Il sito è servito da una sottocartella su GitHub Pages
// (pdonorio.github.io/panther/), quindi nessun path può essere assoluto.
// Vite sostituisce BASE_URL a build time con `base` di vite.config.ts.
const BASE = import.meta.env.BASE_URL
const DB_URL = `${BASE}panther-core.db`
const IDB_NAME = 'panther'
const IDB_STORE = 'cache'
const KEY_DB = 'core-db'
const KEY_ETAG = 'core-db-etag'

// Schema che QUESTO codice sa interrogare. Il DB vive in IndexedDB e
// sopravvive agli aggiornamenti del bundle: senza questo confronto, dopo un
// cambio di schema il client può aprire per sempre una copia vecchia e fallire
// su tabelle che lì non esistono. Va tenuta allineata a build.py::SCHEMA_VERSION.
const SCHEMA_VERSION = '2'

// --------------------------------------------------------------- IndexedDB

function apriIdb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1)
    req.onupgradeneeded = () => req.result.createObjectStore(IDB_STORE)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function idbGet<T>(key: string): Promise<T | undefined> {
  const db = await apriIdb()
  return new Promise((resolve, reject) => {
    const req = db.transaction(IDB_STORE, 'readonly').objectStore(IDB_STORE).get(key)
    req.onsuccess = () => resolve(req.result as T | undefined)
    req.onerror = () => reject(req.error)
  })
}

async function idbSet(key: string, valore: unknown): Promise<void> {
  const db = await apriIdb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite')
    tx.objectStore(IDB_STORE).put(valore, key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

// ------------------------------------------------------------------ caricamento

let sqlite3: Sqlite3Static | null = null
let db: Database | null = null

export type StatoCaricamento = 'cache' | 'scaricato' | 'aggiornato'

/**
 * Apre in memoria il DB scaricato. `sqlite3_deserialize` vuole un puntatore
 * nell'heap del modulo, non un typed array: FREEONCLOSE gli cede la proprietà
 * di quella memoria, così a `close()` non resta niente da liberare a mano.
 */
function apriDaBytes(buf: ArrayBuffer): Database {
  const s = sqlite3!
  const bytes = new Uint8Array(buf)
  const p = s.wasm.allocFromTypedArray(bytes)
  const d = new s.oo1.DB()
  d.checkRc(
    s.capi.sqlite3_deserialize(
      d.pointer!,
      'main',
      p,
      bytes.byteLength,
      bytes.byteLength,
      s.capi.SQLITE_DESERIALIZE_FREEONCLOSE | s.capi.SQLITE_DESERIALIZE_RESIZEABLE,
    ),
  )
  return d
}

/** Versione di schema dichiarata da un DB già aperto. */
function versioneSchema(d: Database): string {
  try {
    const r = d.exec({
      sql: "SELECT valore FROM meta WHERE chiave = 'schema_version'",
      rowMode: 'object',
      returnValue: 'resultRows',
    }) as unknown as { valore: string }[]
    return r[0]?.valore ?? ''
  } catch {
    // Nemmeno la tabella meta: è una copia troppo vecchia per essere letta.
    return ''
  }
}

/**
 * Apre la copia in cache solo se il suo schema è quello che questo codice sa
 * interrogare. Se non lo è la chiude e la butta: meglio ripartire dalla rete
 * che rispondere male. Offline e con una copia inservibile non si può fare
 * niente di utile, e l'errore lo vede la UI.
 */
function apriSeCompatibile(buf: ArrayBuffer): Database | null {
  const d = apriDaBytes(buf)
  if (versioneSchema(d) === SCHEMA_VERSION) return d
  d.close()
  return null
}

/**
 * Carica il DB, preferendo la copia locale. Ritorna come è andata, così la UI
 * può dire all'operatore se sta lavorando su dati freschi o su cache.
 */
export async function caricaDb(): Promise<StatoCaricamento> {
  // Il modulo logga in console un avviso su OPFS non disponibile: qui il DB
  // sta in memoria e la persistenza è IndexedDB, quindi è atteso.
  sqlite3 ??= await sqlite3InitModule()

  const [bufCache, etagCache] = await Promise.all([
    idbGet<ArrayBuffer>(KEY_DB),
    idbGet<string>(KEY_ETAG),
  ])

  // Offline: se abbiamo una copia si parte comunque. È il caso d'uso primario.
  if (!navigator.onLine && bufCache) {
    const d = apriSeCompatibile(bufCache)
    if (d) {
      db = d
      return 'cache'
    }
    throw new Error('La copia locale è di una versione precedente: serve una connessione per aggiornarla.')
  }

  let risposta: Response
  try {
    risposta = await fetch(DB_URL, {
      headers: etagCache && bufCache ? { 'If-None-Match': etagCache } : {},
      cache: 'no-cache',
    })
  } catch (e) {
    const d = bufCache && apriSeCompatibile(bufCache)
    if (d) {
      db = d
      return 'cache'
    }
    throw e
  }

  if (risposta.status === 304 && bufCache) {
    const d = apriSeCompatibile(bufCache)
    if (d) {
      db = d
      return 'cache'
    }
    // Schema vecchio ma il server dice "non modificato": la copia non si può
    // usare e l'ETag mente. Si riscarica ignorandolo.
    const forzata = await fetch(DB_URL, { cache: 'reload' })
    if (!forzata.ok) throw new Error(`Download del database fallito: HTTP ${forzata.status}`)
    const buf = await forzata.arrayBuffer()
    db = apriDaBytes(buf)
    await idbSet(KEY_DB, buf)
    const etag = forzata.headers.get('ETag')
    if (etag) await idbSet(KEY_ETAG, etag)
    return 'aggiornato'
  }
  if (!risposta.ok) {
    const d = bufCache && apriSeCompatibile(bufCache)
    if (d) {
      db = d
      return 'cache'
    }
    throw new Error(`Download del database fallito: HTTP ${risposta.status}`)
  }

  const buf = await risposta.arrayBuffer()
  db = apriDaBytes(buf)

  const etag = risposta.headers.get('ETag')
  await idbSet(KEY_DB, buf)
  if (etag) await idbSet(KEY_ETAG, etag)

  return bufCache ? 'aggiornato' : 'scaricato'
}

function richiediDb(): Database {
  if (!db) throw new Error('Database non caricato: chiamare prima caricaDb()')
  return db
}

/** Righe come oggetti. `exec` gestisce da sé prepare/step/finalize. */
function righe<T>(sql: string, bind?: Record<string, unknown>): T[] {
  return richiediDb().exec({
    sql,
    bind: bind as never,
    rowMode: 'object',
    returnValue: 'resultRows',
  }) as unknown as T[]
}

// ----------------------------------------------------------------------- query

export type Tabella = 'reati_cp' | 'cds'

export interface Risultato {
  id: number
  articolo: string
  titolo: string
  sintesi_operativa: string
}

/**
 * Ricerca full-text. In intervento si digita in fretta e senza accenti: la
 * tokenizzazione FTS usa `remove_diacritics 2`, quindi "velocita" trova
 * "velocità". Ogni termine riceve `*` per il match a prefisso.
 */
export function cerca(tabella: Tabella, query: string, limite = 50): Risultato[] {
  const termini = query
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    // Gli operatori FTS5 nell'input utente romperebbero la query.
    .map((t) => t.replace(/["*^:()-]/g, ''))
    .filter(Boolean)
    .map((t) => `"${t}"*`)

  if (termini.length === 0) return []

  return righe<Risultato>(
    `SELECT t.id, t.articolo, t.titolo, t.sintesi_operativa
       FROM ${tabella}_fts f
       JOIN ${tabella} t ON t.id = f.rowid
      WHERE ${tabella}_fts MATCH $q
      ORDER BY bm25(${tabella}_fts, 10.0, 5.0, 1.0)
      LIMIT $lim`,
    { $q: termini.join(' AND '), $lim: limite },
  )
}

/** Ricerca diretta per numero di articolo — la scorciatoia più usata. */
export function perArticolo(tabella: Tabella, articolo: string): Risultato | null {
  const r = righe<Risultato>(
    `SELECT id, articolo, titolo, sintesi_operativa FROM ${tabella} WHERE articolo = $a`,
    { $a: articolo.trim().toLowerCase() },
  )
  return r[0] ?? null
}

/**
 * Data di rivalutazione ISTAT degli importi (art. 195 c.d.s.). Resta vuota
 * finché il contenuto editoriale non è scritto: in quel caso la UI non deve
 * tacere, deve dire che gli importi a schermo non sono rivalutati.
 */
export function importiAggiornatiAl(articolo: string): string {
  const r = righe<{ importi_aggiornati_al: string }>(
    'SELECT importi_aggiornati_al FROM cds WHERE articolo = $a',
    { $a: articolo.trim().toLowerCase() },
  )
  return r[0]?.importi_aggiornati_al ?? ''
}

export interface TestoIntegrale {
  articolo: string
  rubrica: string
  commi: string[]
  aggiornamenti: string[]
}

/**
 * Testo integrale, scaricato on-demand. Non è nel DB per non gonfiare il
 * bundle iniziale; il service worker lo mette in cache dopo la prima lettura.
 */
export async function testoIntegrale(
  tabella: Tabella,
  articolo: string,
): Promise<TestoIntegrale> {
  const r = await fetch(`${BASE}testi/${tabella}/${encodeURIComponent(articolo)}.json`)
  if (!r.ok) throw new Error(`Testo non disponibile (HTTP ${r.status})`)
  return r.json()
}

/** Metadati di build: la UI DEVE mostrare vigenza e data di aggiornamento. */
export function meta(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const r of righe<{ chiave: string; valore: string }>(
    'SELECT chiave, valore FROM meta',
  )) {
    out[r.chiave] = r.valore
  }
  return out
}
