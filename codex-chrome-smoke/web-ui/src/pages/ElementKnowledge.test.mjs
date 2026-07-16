import assert from "node:assert/strict";

function matchesSearch(item, query) {
  if (!query.trim()) return true;
  const q = query.trim().toLowerCase();
  return [
    item.element_id,
    item.page_id,
    item.name,
    item.human_en,
    item.human_zh?.join(" "),
    item.text,
    item.placeholder,
    item.healing_issue,
    item.healing_suggestion,
    item.last_error,
    item.selectors?.join(" "),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(q);
}

function filterElements(elements, query, risk, healing) {
  return elements.filter((item) => {
    if (!matchesSearch(item, query)) return false;
    if (risk !== "all" && (item.risk_level || "low") !== risk) return false;
    const hasHealing = Boolean(item.healing_issue || item.healing_suggestion);
    if (healing === "with-healing" && !hasHealing) return false;
    if (healing === "without-healing" && hasHealing) return false;
    return true;
  });
}

function elementIdentity(item) {
  const selectors = (item.selectors || []).map((value) => value.trim().toLowerCase()).filter(Boolean).sort().join("|");
  const actions = (item.actions || []).map((value) => value.trim().toLowerCase()).filter(Boolean).sort().join("|");
  const fallback = [item.tag, item.role, item.type, item.text, item.placeholder].map((value) => String(value || "").trim().toLowerCase()).join("|");
  return [item.page_id || "unknown", selectors || fallback, actions].join("::");
}

function dedupeElements(elements) {
  const groups = new Map();
  for (const item of elements) {
    const key = elementIdentity(item);
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return [...groups.values()].map((records) => ({
    ...records.find((item) => item.state === "default") || records[0],
    duplicate_count: records.length,
    states: [...new Set(records.map((item) => item.state || "default"))],
    source_element_ids: records.map((item) => item.element_id || item.name || "unknown"),
  }));
}

function targetMetadataFromUrl(value) {
  try {
    const url = new URL(value.trim());
    const route = (url.hash ? url.hash.slice(1).split("?")[0] : url.pathname).replace(/^\/+/, "");
    const pageId = route
      .split("/")
      .filter(Boolean)
      .join("-")
      .replace(/[^a-zA-Z0-9_\-\u4e00-\u9fff]/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "page";
    return { pageId, name: pageId === "login" ? "登录页" : route ? `页面：${route}` : url.hostname };
  } catch {
    return { pageId: "page", name: "目标页面" };
  }
}

const elements = [
  { element_id: "users.create_button", page_id: "users", text: "新增用户", risk_level: "low", healing_issue: "target_not_visible" },
  { element_id: "users.delete_button", page_id: "users", text: "删除用户", risk_level: "high" },
  { element_id: "login.username_input", page_id: "login", placeholder: "账号", risk_level: "low" },
];

assert.equal(matchesSearch(elements[0], "新增"), true);
assert.equal(matchesSearch(elements[0], "login"), false);
assert.deepEqual(filterElements(elements, "users", "all", "all").map((item) => item.element_id), ["users.create_button", "users.delete_button"]);
assert.deepEqual(filterElements(elements, "", "high", "all").map((item) => item.element_id), ["users.delete_button"]);
assert.deepEqual(filterElements(elements, "", "all", "with-healing").map((item) => item.element_id), ["users.create_button"]);
assert.deepEqual(filterElements(elements, "", "all", "without-healing").map((item) => item.element_id), ["users.delete_button", "login.username_input"]);

const uniqueElements = dedupeElements([
  { element_id: "devices.delete_default", page_id: "devices", state: "default", selectors: ["button.delete"], actions: ["click"] },
  { element_id: "devices.delete_menu", page_id: "devices", state: "dropdown:more", selectors: ["button.delete"], actions: ["click"] },
  { element_id: "users.delete", page_id: "users", state: "default", selectors: ["button.delete"], actions: ["click"] },
]);
assert.equal(uniqueElements.length, 2);
assert.deepEqual(uniqueElements[0].states, ["default", "dropdown:more"]);
assert.equal(uniqueElements[0].duplicate_count, 2);
assert.deepEqual(uniqueElements[0].source_element_ids, ["devices.delete_default", "devices.delete_menu"]);
assert.deepEqual(targetMetadataFromUrl("https://host/#/login?redirect=%2Fredirect"), { pageId: "login", name: "登录页" });
assert.deepEqual(targetMetadataFromUrl("https://host/#/hubble/device"), { pageId: "hubble-device", name: "页面：hubble/device" });

console.log("ElementKnowledge filter tests passed");
