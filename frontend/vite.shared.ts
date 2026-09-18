import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export function appConfig(appName: string) {
  return defineConfig({
    base: './',
    plugins: [vue()],
    resolve: {
      alias: [
        {
          find: '@memory-palace/design-tokens/tokens.css',
          replacement: fileURLToPath(
            new URL('./packages/design-tokens/src/tokens.css', import.meta.url),
          ),
        },
        {
          find: '@memory-palace/api-client',
          replacement: fileURLToPath(
            new URL('./packages/api-client/src/index.ts', import.meta.url),
          ),
        },
        {
          find: '@memory-palace/design-tokens',
          replacement: fileURLToPath(
            new URL('./packages/design-tokens/src/index.ts', import.meta.url),
          ),
        },
        {
          find: '@memory-palace/domain-ui',
          replacement: fileURLToPath(
            new URL('./packages/domain-ui/src/index.ts', import.meta.url),
          ),
        },
      ],
    },
    build: {
      outDir: fileURLToPath(
        new URL(`../static/client/${appName}`, import.meta.url),
      ),
      emptyOutDir: true,
    },
  })
}