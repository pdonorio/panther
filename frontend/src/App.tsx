import { useEffect, useMemo, useState } from 'react'
import {
  caricaDb,
  cerca,
  importiAggiornatiAl,
  meta,
  perArticolo,
  testoIntegrale,
  type Risultato,
  type StatoCaricamento,
  type Tabella,
  type TestoIntegrale,
} from './db'

const TABELLE: { id: Tabella; label: string }[] = [
  { id: 'reati_cp', label: 'Codice Penale' },
  { id: 'cds', label: 'Codice della Strada' },
]

// L'input "575" o "art 575" deve saltare dritto all'articolo, senza FTS.
const RE_SOLO_NUMERO = /^(?:art\.?\s*)?(\d+(?:\s*-?\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))*)$/i

export default function App() {
  const [stato, setStato] = useState<StatoCaricamento | 'caricamento' | 'errore'>('caricamento')
  const [errore, setErrore] = useState('')
  const [tabella, setTabella] = useState<Tabella>('reati_cp')
  const [query, setQuery] = useState('')
  const [risultati, setRisultati] = useState<Risultato[]>([])
  const [aperto, setAperto] = useState<TestoIntegrale | null>(null)
  const [importiAl, setImportiAl] = useState('')
  const [metadati, setMetadati] = useState<Record<string, string>>({})

  useEffect(() => {
    caricaDb()
      .then((s) => {
        setStato(s)
        setMetadati(meta())
      })
      .catch((e: unknown) => {
        setStato('errore')
        setErrore(e instanceof Error ? e.message : String(e))
      })
  }, [])

  useEffect(() => {
    if (stato === 'caricamento' || stato === 'errore') return
    const q = query.trim()
    if (!q) return setRisultati([])

    const m = RE_SOLO_NUMERO.exec(q)
    if (m) {
      const diretto = perArticolo(tabella, m[1].replace(/\s+/g, '').toLowerCase())
      if (diretto) return setRisultati([diretto])
    }
    setRisultati(cerca(tabella, q))
  }, [query, tabella, stato])

  const badge = useMemo(() => {
    switch (stato) {
      case 'cache':
        return 'offline · dati locali'
      case 'scaricato':
        return 'database scaricato'
      case 'aggiornato':
        return 'database aggiornato'
      default:
        return ''
    }
  }, [stato])

  if (stato === 'caricamento') return <main className="centro">Caricamento archivio…</main>
  if (stato === 'errore')
    return (
      <main className="centro">
        <p>Impossibile caricare l'archivio.</p>
        <p className="fioco">{errore}</p>
      </main>
    )

  return (
    <main>
      <header>
        <h1>Panther</h1>
        <span className="badge">{badge}</span>
      </header>

      <nav className="tab">
        {TABELLE.map((t) => (
          <button
            key={t.id}
            className={t.id === tabella ? 'attivo' : ''}
            onClick={() => {
              setTabella(t.id)
              setAperto(null)
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <input
        className="ricerca"
        type="search"
        inputMode="search"
        autoFocus
        placeholder="Articolo o parola chiave…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      <ul className="risultati">
        {risultati.map((r) => (
          <li key={r.id}>
            <button
              onClick={() => {
                setAperto(null)
                setImportiAl(tabella === 'cds' ? importiAggiornatiAl(r.articolo) : '')
                testoIntegrale(tabella, r.articolo).then(setAperto).catch(() => setAperto(null))
              }}
            >
              <span className="art">Art. {r.articolo}</span>
              <span className="tit">{r.titolo || '—'}</span>
              {r.sintesi_operativa && <span className="sintesi">{r.sintesi_operativa}</span>}
            </button>
          </li>
        ))}
        {query.trim() && risultati.length === 0 && (
          <li className="fioco vuoto">
            Nessun risultato.
            {/* La FTS indicizza articolo/titolo/sintesi: finché la sintesi
                operativa non è redatta, la ricerca per concetto è limitata. */}
          </li>
        )}
      </ul>

      {aperto && (
        <section className="testo">
          <button className="chiudi" onClick={() => setAperto(null)} aria-label="Chiudi">
            ×
          </button>
          <h2>
            Art. {aperto.articolo} — {aperto.rubrica}
          </h2>
          {/* Art. 195 c.d.s.: gli importi vanno rivalutati ogni due anni e il
              testo dell'articolo non lo riflette. Finché il dato editoriale
              non c'è, l'unica versione onesta è dirlo su ogni schermata che
              mostra un importo. */}
          {tabella === 'cds' && (
            <p className="avviso">
              {importiAl
                ? `Importi aggiornati al ${importiAl}.`
                : 'Importi non rivalutati (art. 195 c.d.s.): verificare la cifra vigente prima di contestare.'}
            </p>
          )}
          {aperto.commi.map((c, i) => (
            <p key={i}>{c}</p>
          ))}
          {aperto.aggiornamenti.length > 0 && (
            <details>
              <summary>Cronologia modifiche ({aperto.aggiornamenti.length})</summary>
              {aperto.aggiornamenti.map((a, i) => (
                <p key={i} className="fioco">
                  {a}
                </p>
              ))}
            </details>
          )}
        </section>
      )}

      {/* Gli obblighi di licenza stanno nella tabella meta e non solo nei
          documenti proprio perché la UI non possa ometterli. */}
      <footer className="fioco">
        Fonte: {metadati.fonte} · build {metadati.build_date} · vigente
        <br />
        {metadati.disclaimer}
        {metadati.attribuzione && (
          <>
            <br />
            {metadati.attribuzione}
          </>
        )}
        {metadati.licenza && (
          <>
            <br />
            Testi in{' '}
            <a href={metadati.licenza_url} target="_blank" rel="noopener noreferrer">
              {metadati.licenza}
            </a>{' '}
            · <a href={`${import.meta.env.BASE_URL}licenza-dati.html`}>Dettagli sulla licenza</a>
          </>
        )}
      </footer>
    </main>
  )
}
