/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { offline } from "./offline.ts";

// The site is served from https://josh-logue.github.io/Heddle/, so built asset URLs need
// the /Heddle/ prefix. The dev server keeps "/" so localhost works as usual.
export default defineConfig(({ command, isPreview }) => ({
  // (`vite preview` serves the built site, so it needs the built prefix too.)
  base: command === "build" || isPreview ? "/Heddle/" : "/",
  plugins: [react(), offline()],
  // The demo boards are read from ../examples, outside this folder.
  server: { fs: { allow: [".."] } },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    // Core and board tests run in Node: those folders must not touch browser APIs.
    environment: "node",
    include: ["tests/**/*.test.ts", "src/**/*.test.ts"],
  },
}));
