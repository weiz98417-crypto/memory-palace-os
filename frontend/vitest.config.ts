import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@memory-palace/api-client': fileURLToPath(
        new URL('./packages/api-client/src/index.ts', import.meta.url),
      ),
      '@memory-palace/design-tokens': fileURLToPath(
        new URL('./packages/design-tokens/src/index.ts', import.meta.url),
      ),
      '@memory-palace/domain-ui': fileURLToPath(
        new URL('./packages/domain-ui/src/index.ts', import.meta.url),
      ),
    },
  },
  test: {
    environment: 'jsdom',
    restoreMocks: true,
    pool: 'threads',
    maxWorkers: 1,
    fileParallelism: false,
  },
})