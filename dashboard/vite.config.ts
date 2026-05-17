import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://dashboard-api:8100',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://dashboard-api:8100',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
