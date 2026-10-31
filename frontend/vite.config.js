import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Forward /api calls to FastAPI, so the browser sees a single origin.
    // 127.0.0.1, not "localhost": Node resolves localhost to IPv6 (::1), but uvicorn listens on IPv4.
    proxy: { "/api": process.env.API_URL || "http://127.0.0.1:8000" },
  },
});
