import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// 构建产物输出到 public/assets/（随 git 提交），由 FastAPI 静态托管；
// 开发时 bun run dev 起 Vite 服务器，/api 代理到本机 dev 实例。
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { "/api": "http://127.0.0.1:3080" },
  },
  build: {
    outDir: "../public/assets",
    emptyOutDir: true, // assets/ 目录专属 Vite 产物，可安全清空
    sourcemap: false,
    rollupOptions: {
      input: "src/main.js",
      output: {
        // 固定文件名（不带 hash），public/index.html 可以稳定引用
        entryFileNames: "settings-app.js",
        chunkFileNames: "chunk-[name].js",
        assetFileNames: "settings-app.[ext]",
      },
    },
  },
});
