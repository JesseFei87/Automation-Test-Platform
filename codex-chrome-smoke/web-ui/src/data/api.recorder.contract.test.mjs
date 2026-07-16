import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

test("recorder start request uses the API start_url field", async () => {
  const source = await readFile(resolve("src/data/api.ts"), "utf8");

  assert.match(source, /createRecorderSession: \(payload: \{ start_url: string;/);
  assert.doesNotMatch(source, /createRecorderSession: \(payload: \{ entry_url: string;/);
});
