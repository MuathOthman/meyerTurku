import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// All data comes from the FastAPI backend. In production it serves this build on the same
// origin, so the proxy below only matters for `npm run dev`.
export default defineConfig({
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), react()],
  resolve: { tsconfigPaths: true },
  server: {
    port: 5173,
    proxy: { "/api": process.env["KEEL_API_URL"] ?? "http://127.0.0.1:8000" },
  },
});
