import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 相对路径 base，构建产物可被任意静态服务器（含导出脚本内置服务器）直接打开
export default defineConfig({
  base: './',
  plugins: [react()],
  server: { port: 5173 },
  build: { target: 'es2020', chunkSizeWarningLimit: 2000 },
});
