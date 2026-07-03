import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// This UI intentionally runs on its own port, separate from the main
// DocuMind frontend (5180) — it's a standalone benchmarking tool that talks
// to the DocuMind API over HTTP, it does not share a build with the app.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5190,
    proxy: {
      "/api": {
        target: process.env.VITE_BENCHMARK_API_URL || "http://localhost:8020",
        changeOrigin: true,
      },
    },
  },
});
