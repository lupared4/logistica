import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 8000,
    open: true
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['alpinejs', 'chart.js', 'xlsx']
        }
      }
    }
  },
  optimizeDeps: {
    include: ['alpinejs', 'chart.js', 'chartjs-plugin-datalabels', 'xlsx']
  }
});
