import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules\/(cytoscape-cose-bilkent|cose-base|layout-base)\//.test(id)) return 'memory-graph-layout'
          if (/node_modules\/(cytoscape|react-cytoscapejs)\//.test(id)) return 'memory-graph-core'
          return undefined
        }
      }
    }
  },
  server: {
    host: '0.0.0.0'
  }
})
