import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["src/**/*.test.ts"], environment: "node" },
  resolve: {
    alias: {
      "server-only": fileURLToPath(new URL("./src/lib/__tests__/stubs/server-only.ts", import.meta.url)),
    },
  },
});
