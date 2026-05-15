import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5180,
    headers: {
      'Cache-Control': 'no-cache, no-store, must-revalidate',
    },
    proxy: {
      '/api': {
        target: 'http://backend:8010',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://backend:8010',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/auth/, '/api/v1/auth'),
      },
      '/health': {
        target: 'http://backend:8010',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://backend:8010',
        ws: true,
      },
    },
  },
})
