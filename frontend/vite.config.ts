import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "travelmate-rendered-pages-inspector",
      configureServer(server) {
        server.middlewares.use("/__rendered_pages", async (_req, res) => {
          try {
            if (
              typeof (globalThis as any).window === "undefined" ||
              !(globalThis as any).window.localStorage
            ) {
              const fakeStorage = {
                getItem: () => null,
                setItem: () => {},
                removeItem: () => {},
                clear: () => {},
              };
              const fakeDoc = {
                createElement: () => ({
                  style: {},
                  setAttribute: () => {},
                  getElementsByTagName: () => [],
                }),
                documentElement: { style: {} },
                getElementsByTagName: () => [],
                body: { style: {} },
              };
              (globalThis as any).window = {
                __SSR_SHIM__: true,
                screen: {},
                devicePixelRatio: 1,
                navigator: { userAgent: "node-ssr", platform: "linux" },
                document: fakeDoc,
                localStorage: fakeStorage,
                sessionStorage: fakeStorage,
              };
              (globalThis as any).document = fakeDoc;
              (globalThis as any).localStorage = fakeStorage;
              (globalThis as any).sessionStorage = fakeStorage;
              try {
                (globalThis as any).navigator = (globalThis as any).window.navigator;
              } catch {
                // Node 21+ defines globalThis.navigator as a getter
              }
            }
            const mod = await server.ssrLoadModule("/src/App.tsx");
            const payload = mod.renderTravelerPagesForInspection();
            res.statusCode = 200;
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            res.end(JSON.stringify(payload));
          } catch (err: any) {
            res.statusCode = 500;
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            res.end(
              JSON.stringify({
                error: err?.message || String(err),
                stack: err?.stack || "",
              })
            );
          }
        });
      },
    },
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "TravelMate — Compagnon de Voyage",
        short_name: "TravelMate",
        description:
          "Réservation de vols, hébergements, programme jour par jour et documents de voyage.",
        theme_color: "#0F766E",
        background_color: "#FAFAF8",
        display: "standalone",
      },
    }),
  ],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
  },
});

