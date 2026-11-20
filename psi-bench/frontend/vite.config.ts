import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs on 8765 (./serve). In dev mode requests to /api are proxied there.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 900 },
});
