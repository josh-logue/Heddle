// Refresh the README's "Web version keys" section from src/controls.md (npm run help).
import { readFileSync, writeFileSync } from "node:fs";
import { readmeWithControls } from "../src/core/helpText.ts";

const readmePath = new URL("../../README.md", import.meta.url);
const controls = readFileSync(new URL("../src/controls.md", import.meta.url), "utf-8");
const old = readFileSync(readmePath, "utf-8");
const updated = readmeWithControls(old, controls);
if (updated !== old) writeFileSync(readmePath, updated);
console.log(updated !== old ? "README.md web controls updated" : "README.md web controls already up to date");
