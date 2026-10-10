import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The new UI talks to the backend same-origin (/api, /ws) through this proxy in dev;
// set BACKEND_URL to point it elsewhere, or VITE_API_URL to bypass the proxy entirely.
declare const process: { env: Record<string, string | undefined> };
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: true },
    },
  },
});
