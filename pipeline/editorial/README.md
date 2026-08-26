# Contenuto editoriale

Quello che non esiste in nessuna fonte pubblica e va scritto a mano. Vive qui,
versionato a parte, così il sync notturno da Normattiva non lo sovrascrive mai:
la pipeline riscrive `panther-core.db` da zero ogni notte, questa cartella no.

```
editorial/
  interventi/<slug>.yaml     schede della Top 20
  modulistica/<slug>.yaml    indice dei moduli (i PDF stanno in modulistica/)
  articoli/<tabella>/<art>.yaml   campi per singolo articolo (sintesi, importi)
```

## Le due regole che contano

**Niente arriva in produzione senza una firma.** Una scheda con `autore` o
`verificata_il` vuoti viene scartata dalla build. Il testo di legge lo garantisce
Normattiva; queste schede le garantisce una persona, e deve essere possibile
sapere chi.

**Gli importi non si scrivono a memoria.** L'art. 195 c.d.s. impone la
rivalutazione ISTAT biennale e il testo dell'articolo non la riflette. Quando si
compila `importo_sanzione` va compilato anche `importi_aggiornati_al`, che è la
data a cui quella cifra è verificata. Finché è vuoto la UI dichiara all'operatore
che gli importi non sono aggiornati — ed è giusto che lo faccia.

## Obsolescenza

I riferimenti scritti come `tabella` + `articolo` vengono risolti in fase di
build contro il DB, e la build congela l'hash che l'articolo aveva in quel
momento (`interventi_articoli.hash_al_momento`).

Quando Normattiva pubblica una modifica, l'hash cambia e la build segnala le
schede che citano quell'articolo. È l'unico meccanismo che impedisce a una
scheda di restare convincente dopo che la norma sotto è cambiata — lo stesso
difetto degli importi non rivalutati, in forma generale.

Funziona solo sui riferimenti che Panther ha in archivio. Oggi sono il Codice
Penale e il Codice della Strada: le citazioni al c.p.p. e alle leggi speciali si
scrivono con la sola `citazione`, si mostrano all'operatore e non sono
controllabili. Buona parte della Top 20 ricade in questo caso — vedi
`schema.sql`, tabella `interventi_articoli`.

## Modulistica

I PDF non stanno nel database: vanno in `dist/modulistica/` e li serve GitHub
Pages, presi on-demand e messi in cache dal service worker come i testi
integrali. Qui c'è solo l'indice, che è ciò su cui si cerca e si filtra.

Ogni modello va accompagnato da `provenienza`, cioè l'ufficio o la Questura da
cui viene: la modulistica operativa non è nazionale e un modello senza origine
non è verificabile da chi lo usa.
