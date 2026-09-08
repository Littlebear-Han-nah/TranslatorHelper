import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite 配置文件：配置 React 插件与后端 API 代理
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/outputs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
