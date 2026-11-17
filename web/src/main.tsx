import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./ui/App.tsx";
import { ErrorBoundary } from "./ui/SettingsDialog.tsx";
import { browserHost } from "./platform/browserHost.ts";
import { desktopHost } from "./platform/desktopHost.ts";
import { setHost } from "./platform/host.ts";
import "./ui/app.css";

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing the #root element");

// Where the app runs: in the desktop shell its preload has put a bridge on the page
// (platform/bridge.ts); otherwise a browser.
const host = window.heddleDesktop ? desktopHost(window.heddleDesktop) : browserHost;
setHost(host);

// Works offline once visited, and can be installed (web/offline.ts). Not in development:
// a cached copy would hide your edits.
if (import.meta.env.PROD) host.installOffline();

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
