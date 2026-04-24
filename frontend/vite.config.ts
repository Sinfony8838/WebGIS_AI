import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, "/");
          if (normalized.includes("/node_modules/ol/")) {
            return "ol-vendor";
          }
          if (normalized.includes("/node_modules/react/") || normalized.includes("/node_modules/react-dom/")) {
            return "react-vendor";
          }
        }
      }
    }
  },
  server: {
    host: "127.0.0.1",
    port: 5173
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/vitest.setup.ts"
  }
});
