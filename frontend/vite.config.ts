import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['sql-wasm.wasm'],
      manifest: {
        name: 'Panther — Toolkit Operativo',
        short_name: 'Panther',
        lang: 'it',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#0b0f14',
        theme_color: '#0b0f14',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        // Il .db non passa dal precache: lo gestisce db.ts via IndexedDB+ETag.
        globPatterns: ['**/*.{js,css,html,wasm,png,svg}'],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        navigateFallbackDenylist: [/^\/testi\//, /^\/panther-core\.db$/],
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
