import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "")
  const vitePort = Number(env.VITE_PORT || "5145")
  const apiTarget = env.VITE_DEV_API_TARGET || "http://localhost:8890"

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      host: "0.0.0.0",
      port: vitePort,
      proxy: {
        "/auth": { target: apiTarget, changeOrigin: true },
        "/chat": { target: apiTarget, changeOrigin: true, ws: true },
        "/artifacts": { target: apiTarget, changeOrigin: true },
        "/admin": { target: apiTarget, changeOrigin: true },
        "/health": { target: apiTarget, changeOrigin: true },
        "/docs": { target: apiTarget, changeOrigin: true },
        "/openapi.json": { target: apiTarget, changeOrigin: true },
      },
    },
  }
})
