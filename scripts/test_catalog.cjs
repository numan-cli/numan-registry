"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const catalog = require("../registry/catalog.js");
const root = path.resolve(__dirname, "..");
const packages = JSON.parse(fs.readFileSync(path.join(root, "registry/index.json"), "utf8")).packages;
const filters = { q: "", type: "", nu: "", target: "", only: false };
const windows = "x86_64-pc-windows-msvc";
const linux = "x86_64-unknown-linux-gnu";

test("Nu grammar agrees with the registry validator, including range boundaries", () => {
  const constraints = [...new Set(packages.flatMap(p => p.versions.map(v => v.nu_version)))].concat([
    "0.114.1", "=0.114.x", "0.114.*", "=0.114.1", ">0.114.0 <=0.114.2", ">=0.114.0 0.114.X",
  ]);
  const versions = ["0.0.0", "0.92.0", "0.113.9", "0.114.0", "0.114.1", "0.114.2", "0.115.0", "1.0.0", "banana", "0.114.1-beta", "0.114.1.0", "00.114.1"];
  const cases = constraints.flatMap(c => versions.map(v => [c, v]));
  const python = spawnSync(process.env.PYTHON || "python", ["-c", `
import json, sys
sys.path.insert(0, 'scripts')
from nu_version_constraint import matches_nu_constraint
def match(c, v):
    try: return matches_nu_constraint(v, c)
    except ValueError: return None
print(json.dumps([match(c, v) for c, v in json.load(sys.stdin)]))
`], { cwd: root, input: JSON.stringify(cases), encoding: "utf8" });
  assert.equal(python.status, 0, python.stderr);
  const expected = JSON.parse(python.stdout);
  cases.forEach(([c, v], i) => assert.equal(catalog.matchesNu(c, v), expected[i], `${c} / ${v}`));
});

test("invalid Nu versions never produce compatibility claims", () => {
  for (const value of ["banana", "0.114", "0.114.1junk", "0.114.1-beta", "01.114.1", "9007199254740992.0.0"]) {
    assert.equal(catalog.parseNu(value), null);
    assert.equal(catalog.matchesNu("*", value), null);
  }
  for (const constraint of ["", "^0.114.0", ">=0.114.0 invalid"]) {
    assert.equal(catalog.matchesNu(constraint, "0.114.1"), null);
  }
});

test("latest follows intake order, not lexical or semver sorting", () => {
  const versions = [{ version: "9.0.0" }, { version: "0.1.0-commit" }];
  assert.equal(catalog.latest({ versions }), versions[1]);
});

test("platform matching distinguishes binary targets, untargeted archives and source builds", () => {
  const version = { artifact: { kind: "binary", targets: { [windows]: {} } } };
  assert.equal(catalog.targetMatches(version, windows), true);
  assert.equal(catalog.targetMatches(version, linux), false);
  assert.equal(catalog.targetMatches({ artifact: { kind: "archive" } }, linux), true);
  assert.equal(catalog.targetMatches({ artifact: { kind: "source" } }, linux), false);
  assert.equal(catalog.targetMatches({ artifact: { kind: "binary" } }, linux), false);
});

test("search, type, target and Nu filters combine without hiding invalid-input results", () => {
  const p = { id: { owner: "owner", name: "name" }, type: "plugin", description: "image processor", tags: ["pictures"], versions: [{ version: "1.0.0", nu_version: ">=0.114.0 <0.115.0", artifact: { kind: "binary", targets: { [windows]: {} } } }] };
  assert.equal(catalog.filterPackages([p], { ...filters, q: "PICTURES", target: windows, nu: "0.114.1", only: true }).length, 1);
  for (const change of [{ q: "missing" }, { type: "module" }, { target: linux }, { nu: "0.115.0", only: true }]) {
    assert.equal(catalog.filterPackages([p], { ...filters, ...change }).length, 0);
  }
  assert.equal(catalog.filterPackages([p], { ...filters, nu: "banana", only: true }).length, 1);
});

test("activation guidance follows version metadata and never activates install-only packages", () => {
  const module = { type: "module" };
  assert.equal(catalog.canActivate(module, { activation: { kind: "nu-module" }, artifact: { entry: "mod.nu" } }), true);
  assert.equal(catalog.canActivate(module, { artifact: { entry: "mod.nu" } }), false);
  assert.equal(catalog.canActivate(module, { activation: { kind: "nu-module" } }), false);
  assert.equal(catalog.canActivate(module, { activation: { kind: "nu-module" }, artifact: { entry: "mod.nu" }, dependencies: { "owner/dep": "1.0.0" } }), false);
  assert.equal(catalog.canActivate(module, { activation: { kind: "nu-module", import: "unknown" }, artifact: { entry: "mod.nu" } }), false);
  packages.forEach(p => p.versions.forEach(v => {
    const html = catalog.detailHtml(p, v, filters);
    assert.equal(html.includes("numan activate "), catalog.canActivate(p, v), `${p.id.owner}/${p.id.name}@${v.version}`);
    assert.ok(html.includes(`numan install ${p.id.owner}/${p.id.name}@${v.version}`));
    assert.ok(html.includes("Lifecycle-tested Nu"));
    assert.ok(html.includes("SHA256:"));
    if (catalog.canActivate(p, v) && !(v.verified_with || []).length && v.evidence_tier !== "provisional") {
      assert.ok(html.includes("Lifecycle proof is missing"), `${p.id.owner}/${p.id.name}@${v.version}`);
    }
  }));
  const missingVersion = { version: "1.0.0", activation: { kind: "nu-module" }, artifact: { entry: "mod.nu" } };
  assert.ok(catalog.detailHtml({ id: { owner: "o", name: "n" }, type: "module" }, missingVersion, filters).includes("Lifecycle proof is missing"));
});

test("untrusted catalog text and links cannot inject markup or shell commands", () => {
  const p = { id: { owner: "owner", name: "bad;command" }, type: "script", description: '<img src=x onerror="alert(1)">', repo: "javascript:alert(1)", tags: ["<script>"], versions: [] };
  const v = { version: "1.0.0", artifact: { kind: "archive", url: 'https://example.com/" onclick="bad', sha256: "<unsafe>" }, evidence_tier: "provisional", deferral_reason: "<unsafe>", source: { git: "javascript:alert(1)", rev: "<unsafe>" } };
  p.versions.push(v);
  const html = catalog.detailHtml(p, v, filters);
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(!html.includes("numan install "));
  assert.ok(html.includes("&lt;unsafe&gt;"));
  assert.ok(html.includes("Provisional:"));
  assert.equal(catalog.safeUrl("javascript:alert(1)"), "");
});

test("deep links round-trip package IDs and selected versions", () => {
  const hash = catalog.packageHash("owner/a+b", "0.1.0+build.1");
  const params = new URLSearchParams(hash.slice(1));
  assert.equal(params.get("package"), "owner/a+b");
  assert.equal(params.get("version"), "0.1.0+build.1");
});

test("publication metadata is informational, validated, and distinguishes staging", () => {
  const metadata = { built_at: "2026-10-18T12:00:00Z", source_revision: "a".repeat(40), environment: "staging" };
  assert.match(catalog.publicationHtml(metadata), /Staging publication build · not production trust/);
  assert.match(catalog.publicationHtml(metadata), /unsigned metadata is informational/);
  assert.equal(catalog.publicationHtml({ ...metadata, source_revision: '<script>alert(1)</script>' }), "");
  assert.equal(catalog.publicationHtml({ ...metadata, built_at: "invalid" }), "");
});
