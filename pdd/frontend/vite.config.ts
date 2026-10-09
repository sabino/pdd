/// <reference types="vitest/config" />
import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { configDefaults } from 'vitest/config';

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, '.', '');
    const apiUrl = env.VITE_API_URL || 'http://127.0.0.1:9876';

    return {
      server: {
        port: 3000,
        host: '0.0.0.0',
        proxy: {
          '/api/': {
            target: apiUrl,
            changeOrigin: true,
          },
          '/ws': {
            target: apiUrl.replace('http', 'ws'),
            ws: true,
          },
        },
      },
      plugins: [react(), tailwindcss()],
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      },
      test: {
        environment: 'jsdom',
        globals: true,
        setupFiles: ['./tests/setup.ts'],
        exclude: [...configDefaults.exclude, '**/._*'],
      },
    };
});
