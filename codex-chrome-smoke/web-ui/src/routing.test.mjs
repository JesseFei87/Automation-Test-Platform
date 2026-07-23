import assert from "node:assert/strict";
import test from "node:test";
import { buildAppHash, parseAppRoute } from "./routing.ts";

test("top-level pages round-trip through hashes", () => {
  for (const page of ["dashboard", "projects", "requirements", "ai-generate", "test-points", "cases", "recorder", "ai-test", "reports", "element-knowledge", "settings"]) {
    const route = parseAppRoute(`#/${page === "dashboard" ? "" : page}`);
    assert.equal(buildAppHash(route), `#/${page === "dashboard" ? "" : page}`);
  }
});

test("detail routes and the legacy case route remain addressable", () => {
  assert.deepEqual(parseAppRoute("#/reports/ui-123"), { page: "reports", runId: "ui-123" });
  assert.deepEqual(parseAppRoute("#/ai-test/ui-456"), { page: "execution", runId: "ui-456" });
  assert.deepEqual(parseAppRoute("#case-toolbox?draft=42"), { page: "cases", draftId: 42 });
  assert.deepEqual(parseAppRoute("#/missing", "projects"), { page: "projects" });
});
