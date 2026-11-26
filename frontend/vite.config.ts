import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    proxy: { "/api": "http://127.0.0.1:8766" },
  },
  build: {
    outDir: "dist",
    // The server sends a default-src self CSP: never inline assets as data: URIs.
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/__tests__/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/__tests__/**", "src/main.tsx"],
    },
  },
});
