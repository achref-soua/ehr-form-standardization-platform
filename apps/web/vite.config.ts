import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      thresholds: { statements: 90, branches: 90, functions: 90, lines: 90 },
      exclude: [
        "src/main.tsx",
        "src/api/generated.ts",
        "src/api/openapi-schema.ts",
        "src/test/**",
        "src/**/*.test.{ts,tsx}",
      ],
    },
  },
});
