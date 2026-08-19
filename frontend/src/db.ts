/**
 * Caricamento e query del database Panther lato client.
 *
 * Strategia (vedi boot_up.yaml -> delivery.split):
 *   1. `panther-core.db` (~0.5MB) scaricato una volta e tenuto in IndexedDB.
 *   2. Rivalidazione via ETag a ogni avvio: se il server risponde 304 si usa
 *      la copia locale, quindi a regime l'avvio è offline e istantaneo.
 *   3. Il testo integrale NON è nel DB: si prende on-demand da /testi/.
 */

import initSqlJs, { type Database, type SqlJsStatic } from 'sql.js'

const DB_URL = '/panther-core.db'
const IDB_NAME = 'panther'
const IDB_STORE = 'cache'
const KEY_DB = 'core-db'
const KEY_ETAG = 'core-db-etag'

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

let sql: SqlJsStatic | null = null
let db: Database | null = null

export type StatoCaricamento = 'cache' | 'scaricato' | 'aggiornato'

/**
 * Carica il DB, preferendo la copia locale. Ritorna come è andata, così la UI
 * può dire all'operatore se sta lavorando su dati freschi o su cache.
 */
export async function caricaDb(): Promise<StatoCaricamento> {
  sql ??= await initSqlJs({ locateFile: (f) => `/${f}` })

  const [bufCache, etagCache] = await Promise.all([
    idbGet<ArrayBuffer>(KEY_DB),
    idbGet<string>(KEY_ETAG),
  ])

  // Offline: se abbiamo una copia si parte comunque. È il caso d'uso primario.
  if (!navigator.onLine && bufCache) {
    db = new sql.Database(new Uint8Array(bufCache))
    return 'cache'
  }

  let risposta: Response
  try {
    risposta = await fetch(DB_URL, {
      headers: etagCache && bufCache ? { 'If-None-Match': etagCache } : {},
      cache: 'no-cache',
    })
  } catch (e) {
    if (bufCache) {
      db = new sql.Database(new Uint8Array(bufCache))
      return 'cache'
    }
    throw e
  }

  if (risposta.status === 304 && bufCache) {
    db = new sql.Database(new Uint8Array(bufCache))
    return 'cache'
  }
  if (!risposta.ok) {
    if (bufCache) {
      db = new sql.Database(new Uint8Array(bufCache))
      return 'cache'
    }
    throw new Error(`Download del database fallito: HTTP ${risposta.status}`)
  }

  const buf = await risposta.arrayBuffer()
  db = new sql.Database(new Uint8Array(buf))

  const etag = risposta.headers.get('ETag')
  await idbSet(KEY_DB, buf)
  if (etag) await idbSet(KEY_ETAG, etag)

  return bufCache ? 'aggiornato' : 'scaricato'
}

function richiediDb(): Database {
  if (!db) throw new Error('Database non caricato: chiamare prima caricaDb()')
  return db
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

  const stmt = richiediDb().prepare(
    `SELECT t.id, t.articolo, t.titolo, t.sintesi_operativa
       FROM ${tabella}_fts f
       JOIN ${tabella} t ON t.id = f.rowid
      WHERE ${tabella}_fts MATCH $q
      ORDER BY bm25(${tabella}_fts, 10.0, 5.0, 1.0)
      LIMIT $lim`,
  )
  stmt.bind({ $q: termini.join(' AND '), $lim: limite })

  const out: Risultato[] = []
  while (stmt.step()) out.push(stmt.getAsObject() as unknown as Risultato)
  stmt.free()
  return out
}

/** Ricerca diretta per numero di articolo — la scorciatoia più usata. */
export function perArticolo(tabella: Tabella, articolo: string): Risultato | null {
  const stmt = richiediDb().prepare(
    `SELECT id, articolo, titolo, sintesi_operativa FROM ${tabella} WHERE articolo = $a`,
  )
  stmt.bind({ $a: articolo.trim().toLowerCase() })
  const r = stmt.step() ? (stmt.getAsObject() as unknown as Risultato) : null
  stmt.free()
  return r
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
  const r = await fetch(`/testi/${tabella}/${encodeURIComponent(articolo)}.json`)
  if (!r.ok) throw new Error(`Testo non disponibile (HTTP ${r.status})`)
  return r.json()
}

/** Metadati di build: la UI DEVE mostrare vigenza e data di aggiornamento. */
export function meta(): Record<string, string> {
  const out: Record<string, string> = {}
  const stmt = richiediDb().prepare('SELECT chiave, valore FROM meta')
  while (stmt.step()) {
    const r = stmt.getAsObject() as { chiave: string; valore: string }
    out[r.chiave] = r.valore
  }
  stmt.free()
  return out
}
