import { defineConfig, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      injectRegister: "auto",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "Odie",
        short_name: "Odie",
        description: "Your personal assistant",
        display: "standalone",
        start_url: "/",
        scope: "/",
        background_color: "#F7F3EE",
        theme_color: "#F7F3EE",
        icons: [
          { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
        ],
      },
      injectManifest: { globPatterns: ["**/*.{js,css,html,svg,png,woff2}"] },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), "../evals/sample"] },  // the #sample screen's chat
  },
  preview: { allowedHosts: [".ts.net"], proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } } },  // branch preview over Tailscale
  test: { environment: "node", setupFiles: ["src/test-setup.ts"] },
} as any);
