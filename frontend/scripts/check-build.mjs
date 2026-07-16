import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(root, "dist/.vite/manifest.json"), "utf8"));
const entryKey = Object.keys(manifest).find((key) => manifest[key].isEntry);
if (!entryKey) throw new Error("Vite manifest has no entry chunk");

const staticClosure = new Set();
const visitStatic = (key) => {
  if (staticClosure.has(key)) return;
  staticClosure.add(key);
  for (const imported of manifest[key]?.imports ?? []) visitStatic(imported);
};
visitStatic(entryKey);
if ([...staticClosure].some((key) => key.toLowerCase().includes("mermaid"))) {
  throw new Error("Mermaid leaked into the entry chunk's static dependency closure");
}
if (!(manifest[entryKey].dynamicImports ?? []).some((key) => key.toLowerCase().includes("mermaid"))) {
  throw new Error("Mermaid is not registered as an entry dynamic import");
}

const forbidden = ["vite.config.js", "vite.config.d.ts"];
for (const filename of forbidden) {
  if (existsSync(join(root, filename))) throw new Error(`Build generated forbidden file: ${filename}`);
}
const buildInfo = readdirSync(root).filter((name) => name.endsWith(".tsbuildinfo"));
if (buildInfo.length) throw new Error(`Build generated tsbuildinfo: ${buildInfo.join(", ")}`);

console.log("Build contract passed: Mermaid is dynamic and TypeScript emitted no artifacts.");
