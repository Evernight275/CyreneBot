import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  base: '/console/',
  plugins: [vue()],
  build: {
    rollupOptions: {
      input: {
        console: 'index.html',
        login: 'login.html',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/ready': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/providers': 'http://127.0.0.1:8000',
      '/chat': 'http://127.0.0.1:8000',
      '/agents': 'http://127.0.0.1:8000',
      '/images': 'http://127.0.0.1:8000',
      '/plugins': 'http://127.0.0.1:8000',
      '/channels': 'http://127.0.0.1:8000',
      '/telegram': 'http://127.0.0.1:8000',
      '/qq': 'http://127.0.0.1:8000',
    },
  },
})
