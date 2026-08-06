import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The API address, from the launcher rather than hard-coded. `tools/dev.py serve
// --with-ui --address 127.0.0.1:9090` started the API on 9090 while this proxy still
// pointed at 8080, so both processes were healthy and every screen was empty.
const apiTarget = `http://${process.env.RETAIL_API_ADDRESS ?? "127.0.0.1:8080"}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/healthz": apiTarget
    }
  }
});
