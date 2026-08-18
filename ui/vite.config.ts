import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The complete dialable API URL comes from the launcher. `tools/dev.py serve
// --with-ui --address 127.0.0.1:9090` starts the API on 9090; keeping the proxy at
// 8080 would leave both processes healthy while every screen stayed empty.
const apiTarget = process.env.RETAIL_API_TARGET ?? "http://127.0.0.1:8080";

// Vite rejects requests whose Host header is not in this allowlist, which blocks
// tunnels (ngrok/cloudflared) used to share the demo. Default to any ngrok
// subdomain (URLs rotate per session); override with RETAIL_ALLOWED_HOSTS as a
// comma list, or "true" to allow every host.
const envHosts = process.env.RETAIL_ALLOWED_HOSTS;
const allowedHosts =
  envHosts === "true"
    ? true
    : envHosts
      ? envHosts.split(",").map((h) => h.trim())
      : [".ngrok-free.app", ".ngrok.app", ".ngrok.io"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    allowedHosts,
    proxy: {
      "/api": apiTarget,
      "/healthz": apiTarget
    }
  }
});
