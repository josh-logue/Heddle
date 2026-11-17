// npm run desktop:dev: the desktop shell on Vite's dev server, so edits show up as you
// save (F12 opens the developer tools). Closing the window stops both.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const web = fileURLToPath(new URL("..", import.meta.url));
// The electron package's main export is the path to its binary.
const electron = createRequire(import.meta.url)("electron") as string;

const server = await createServer({ root: web, server: { port: 5175, strictPort: true } });
await server.listen();
const url = server.resolvedUrls?.local[0] ?? "http://localhost:5175/";
console.log(`Vite at ${url}; starting the desktop shell`);

const child = spawn(electron, [fileURLToPath(new URL("main.ts", import.meta.url))], {
  stdio: "inherit",
  env: { ...process.env, HEDDLE_DEV_URL: url },
});
child.on("exit", (code) => {
  void server.close().then(() => process.exit(code ?? 0));
});
