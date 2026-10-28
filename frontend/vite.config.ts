import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

  return {
    plugins: [vue(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: backend, changeOrigin: true },
      },
    },
  };
});
