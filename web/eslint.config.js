import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
  {
    // The platform seam (W9a): the app reaches the browser only through browserHost, so a
    // desktop shell can supply another host (platform/host.ts).
    files: ["src/**"],
    ignores: ["src/platform/browserHost.ts", "src/platform/desktopHost.ts", "src/platform/browser/**"],
    rules: {
      "no-restricted-globals": ["error", "localStorage", "sessionStorage", "indexedDB", "navigator"],
      "no-restricted-imports": ["error", {
        patterns: [{ group: ["**/browser/*", "**/browserHost*"], message: "Use the host (getHost() in platform/host.ts)." }],
      }],
    },
  },
  {
    files: ["src/main.tsx"],
    rules: { "no-restricted-imports": "off" }, // (chooses the host at startup)
  },
  {
    // core/ and board/ are pure logic that also runs in Node (tests, later the desktop
    // shell). Keep browser globals out so a stray `window` or `document` fails lint.
    files: ["src/core/**", "src/board/**"],
    languageOptions: { globals: {} },
    rules: {
      "no-restricted-globals": [
        "error",
        "window", "document", "localStorage", "indexedDB", "navigator", "location",
      ],
    },
  },
  {
    files: ["*.config.{js,ts}", "tests/**", "e2e/**", "e2e-desktop/**", "desktop/**"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    // The shell's sandboxed preload: CommonJS, by necessity.
    files: ["desktop/**/*.cjs"],
    languageOptions: { sourceType: "commonjs", globals: { ...globals.node } },
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
);
