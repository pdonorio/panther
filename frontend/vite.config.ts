import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// GitHub Pages serve il sito da https://pdonorio.github.io/panther/, non da
// una radice. Tutti i path assoluti devono passare da qui: se un giorno il
// sito finisce su un dominio dedicato, basta rimettere BASE = '/'.
const BASE = '/panther/'

export default defineConfig({
  base: BASE,
  // In dev il pre-bundling di esbuild riscriverebbe l'`import.meta.url` con
  // cui sqlite-wasm trova il proprio .wasm, e il modulo non parte più.
  optimizeDeps: { exclude: ['@sqlite.org/sqlite-wasm'] },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Panther — Toolkit Operativo',
        short_name: 'Panther',
        lang: 'it',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#0b0f14',
        theme_color: '#0b0f14',
        // scope/start_url devono essere espliciti sotto sottocartella: senza,
        // la PWA installata parte dalla radice del dominio e trova un 404.
        scope: BASE,
        start_url: BASE,
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        // Il .db non passa dal precache: lo gestisce db.ts via IndexedDB+ETag.
        // Il .wasm sì: è in assets/ con l'hash nel nome, quindi il precache lo
        // invalida da solo quando sql.js cambia versione.
        globPatterns: ['**/*.{js,css,html,wasm,png,svg}'],
        // sqlite-wasm porta con sé il worker e il proxy OPFS (~250 KB): qui
        // il DB sta in memoria, non li usiamo, e non vanno scaricati all'avvio.
        globIgnores: ['**/sqlite3-worker1-*.js', '**/sqlite3-opfs-async-proxy-*.js'],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        navigateFallbackDenylist: [
          new RegExp(`^${BASE}testi/`),
          new RegExp(`^${BASE}panther-core\\.db$`),
        ],
        runtimeCaching: [
          {
            // I testi per articolo sono immutabili: cache-first, TTL lungo.
            urlPattern: /\/testi\/.*\.json$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'panther-testi',
              expiration: { maxEntries: 1500, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
        ],
      },
    }),
  ],
})
