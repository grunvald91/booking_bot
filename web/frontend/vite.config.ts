import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Include lazy route bundles, fonts and styles in the offline installation.
// Generated filenames are content-hashed, so SW v4 never guesses stale assets.
const offlineAssetManifest: Plugin = {
  name: 'servgo-offline-assets',
  generateBundle(_options, bundle) {
    const files = Object.keys(bundle)
      .filter((name) => name.startsWith('assets/'))
      .map((name) => '/' + name)
    this.emitFile({
      type: 'asset',
      fileName: 'offline-assets.json',
      source: JSON.stringify(files),
    })
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss(), offlineAssetManifest],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
