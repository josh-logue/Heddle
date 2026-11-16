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
    files: ["*.config.{js,ts}", "tests/**"],
    languageOptions: { globals: { ...globals.node } },
  },
);
