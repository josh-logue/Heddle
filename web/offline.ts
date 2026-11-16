// Works offline and can be installed: at build time, writes sw.js, a small service worker
// that keeps every file of this build (so the demo boards open offline too). No plugin
// dependency. Dev builds don't use it (main.tsx registers it in production only).
//
// - Opening the page: the network first (so a new deploy is picked up), the saved copy
//   when offline.
// - Everything else of this build: from the saved copy (file names carry a content hash).
// - A new build replaces the old copy once its service worker takes over (the next visit).
import { createHash } from "node:crypto";
import { readdirSync } from "node:fs";
import type { Plugin } from "vite";

/** Files from public/ that the page uses (served as they are, without hashes). */
function publicFiles(dir: string): string[] {
  try {
    return readdirSync(dir).filter((f) => !f.startsWith("."));
  } catch {
    return [];
  }
}

export function serviceWorkerSource(version: string, files: readonly string[]): string {
  return `// Generated at build time by web/offline.ts: keeps this build of Heddle for offline use.
const CACHE = "heddle-${version}";
const FILES = ${JSON.stringify(["./", ...files])};

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("heddle-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        event.waitUntil(caches.open(CACHE).then((cache) => cache.put("./", copy)));
      }
      return response;
    }).catch(() => caches.match("./", { cacheName: CACHE }).then((hit) => hit ?? Response.error())));
    return;
  }
  // ignoreVary: module scripts are asked for with an Origin header the saved copies weren't,
  // and a server answering "Vary: Origin" would otherwise make every lookup miss.
  event.respondWith(caches.match(request, { cacheName: CACHE, ignoreVary: true }).then((hit) => hit ?? fetch(request)));
});
`;
}

export function offline(publicDir = "public"): Plugin {
  return {
    name: "heddle-offline",
    apply: "build",
    generateBundle(_options, bundle) {
      const built = Object.keys(bundle).filter((f) => !f.endsWith(".map") && f !== "sw.js");
      const files = [...built, ...publicFiles(publicDir)].sort();
      const version = createHash("sha256").update(files.join("\n")).digest("hex").slice(0, 12);
      this.emitFile({ type: "asset", fileName: "sw.js", source: serviceWorkerSource(version, files) });
    },
  };
}
