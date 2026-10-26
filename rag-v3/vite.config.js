import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const isProd = mode === 'production'
  return {
    plugins: [react()],
    server: {
      port: 5173,
    },
    build: {
      target: 'esnext',
      sourcemap: isProd ? 'hidden' : true,
      rollupOptions: {
        output: {
          manualChunks: {
            'vendor':   ['react', 'react-dom'],
            'markdown': ['react-markdown', 'remark-gfm', 'rehype-sanitize'],
            'syntax':   ['react-syntax-highlighter'],
            'virtual':  ['react-virtuoso'],
          },
        },
      },
    },
    esbuild: { drop: isProd ? ['console', 'debugger'] : [] },
    optimizeDeps: {
      include: ['react', 'react-dom', 'react-markdown', 'remark-gfm', 'rehype-sanitize', 'react-virtuoso'],
    },
  }
})
