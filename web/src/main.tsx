import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./ui/App.tsx";
import { ErrorBoundary } from "./ui/SettingsDialog.tsx";
import "./ui/app.css";

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing the #root element");

// Works offline once visited, and can be installed (web/offline.ts). Not in development:
// a cached copy would hide your edits.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => undefined);
  });
}

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
