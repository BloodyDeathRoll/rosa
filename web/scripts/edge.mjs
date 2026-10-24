// Writes the Edge Functions of the Build Output into .vercel/output/functions/. Runs in
// `prepare-output` after csp.mjs. Today one function: /ig (edge/ig.js), the Instagram bio
// redirect. The matching route lives in vercel-output.json before `handle: filesystem`.
import { mkdirSync, copyFileSync, writeFileSync, existsSync } from "node:fs";

const FUNCTIONS = [
  { path: "ig", source: "edge/ig.js", env: ["EDGE_CONFIG"] },
];

for (const f of FUNCTIONS) {
  if (!existsSync(f.source)) throw new Error(`edge: ${f.source} is missing`);
  const dir = `.vercel/output/functions/${f.path}.func`;
  mkdirSync(dir, { recursive: true });
  copyFileSync(f.source, `${dir}/index.js`);
  writeFileSync(
    `${dir}/.vc-config.json`,
    JSON.stringify({ runtime: "edge", entrypoint: "index.js", envVarsInUse: f.env }, null, 2) + "\n",
  );
}
console.log(`edge: ${FUNCTIONS.length} function(s): ${FUNCTIONS.map((f) => "/" + f.path).join(", ")}`);
