import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The complete dialable API URL comes from the launcher. `tools/dev.py serve
// --with-ui --address 127.0.0.1:9090` starts the API on 9090; keeping the proxy at
// 8080 would leave both processes healthy while every screen stayed empty.
const apiTarget = process.env.RETAIL_API_TARGET ?? "http://127.0.0.1:8080";

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
