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
const pythonProbe = `
import sys
sys.path.insert(0, 'scripts')
from nu_version_constraint import matches_nu_constraint
print(sys.executable)
`;

function resolvePython() {
  const candidates = [];
  if (process.env.PYTHON) candidates.push({ command: process.env.PYTHON, args: [] });
  candidates.push({
    command: path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python"),
    args: [],
  });
  if (process.platform === "win32") candidates.push({ command: "py", args: ["-3"] });
  candidates.push({ command: "python3", args: [] }, { command: "python", args: [] });

  for (const candidate of candidates) {
    const probe = spawnSync(candidate.command, [...candidate.args, "-c", pythonProbe], {
      cwd: root,
      encoding: "utf8",
    });
    if (probe.status === 0) return candidate;
  }

  assert.fail(
    "no working Python interpreter found for constraint parity; " +
      "set PYTHON or provide python3/python on PATH"
  );
}

test("Nu grammar agrees with the registry validator, including range boundaries", () => {
  const constraints = [...new Set(packages.flatMap(p => p.versions.map(v => v.nu_version)))].concat([
    "0.114.1", "=0.114.x", "0.114.*", "=0.114.1", ">0.114.0 <=0.114.2", ">=0.114.0 0.114.X",
  ]);
  const versions = ["0.0.0", "0.92.0", "0.113.9", "0.114.0", "0.114.1", "0.114.2", "0.115.0", "1.0.0", "banana", "0.114.1-beta", "0.114.1.0", "00.114.1"];
  const cases = constraints.flatMap(c => versions.map(v => [c, v]));
  const interpreter = resolvePython();
  const python = spawnSync(interpreter.command, [...interpreter.args, "-c", `
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

test("proof coverage groups results by OS and architecture", () => {
  const version = { proofs: [
    { os: "windows", arch: "x86_64", result: "passed" },
    { os: "windows", arch: "x86_64", result: "failed" },
    { os: "linux", arch: "x86_64", result: "passed" },
  ] };
  assert.deepEqual(catalog.proofCoverage(version), [
    { platform: "linux/x86_64", label: "Linux · x64", passed: 1, failed: 0, status: "passed" },
    { platform: "windows/x86_64", label: "Windows · x64", passed: 1, failed: 1, status: "1 passed, 1 failed" },
  ]);
  assert.deepEqual(catalog.proofCoverage({}), []);
});

test("catalog details show per-platform proof coverage", () => {
  const pkg = { id: { owner: "acme", name: "pkg" }, type: "plugin", description: "test", versions: [] };
  const version = { version: "1.0.0", nu_version: "*", artifact: { kind: "archive" }, proofs: [
    { os: "linux", arch: "x86_64", result: "passed" },
    { os: "windows", arch: "x86_64", result: "passed" },
    { os: "windows", arch: "x86_64", result: "failed" },
  ] };
  pkg.versions.push(version);
  const html = catalog.detailHtml(pkg, version, filters);
  assert.ok(html.includes("Lifecycle-proof coverage"));
  assert.ok(html.includes("Linux · x64"));
  assert.ok(html.includes("Windows · x64"));
  assert.ok(html.includes("1 passed, 1 failed"));
  assert.ok(!html.includes("No per-platform proof records"));
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
    if (v.yanked) {
      assert.equal(catalog.canActivate(p, v), false, `${p.id.owner}/${p.id.name}@${v.version}`);
      assert.equal(html.includes("numan install "), false, `${p.id.owner}/${p.id.name}@${v.version}`);
      assert.equal(html.includes("numan activate "), false, `${p.id.owner}/${p.id.name}@${v.version}`);
      assert.ok(html.includes("Version yanked"), `${p.id.owner}/${p.id.name}@${v.version}`);
      assert.ok(html.includes(v.yanked.reason_code), `${p.id.owner}/${p.id.name}@${v.version}`);
    } else {
      assert.equal(html.includes("numan activate "), catalog.canActivate(p, v), `${p.id.owner}/${p.id.name}@${v.version}`);
      assert.ok(html.includes(`numan install ${p.id.owner}/${p.id.name}@${v.version}`));
      if (catalog.canActivate(p, v) && !(v.verified_with || []).length && v.evidence_tier !== "provisional") {
        assert.ok(html.includes("Lifecycle proof is missing"), `${p.id.owner}/${p.id.name}@${v.version}`);
      }
    }
    assert.ok(html.includes("Lifecycle-tested Nu"));
    assert.ok(html.includes("Lifecycle-proof coverage"));
    if ((v.proofs || []).length) assert.ok(!html.includes("No per-platform proof records"));
    assert.ok(html.includes("SHA256:"));
  }));
  const yanked = { version: "9.9.9", yanked: { reason_code: "nu-parser-incompatible", evidence_url: "https://example.com/evidence.md" }, activation: { kind: "nu-module" }, artifact: { entry: "mod.nu" } };
  assert.equal(catalog.canActivate(module, yanked), false);
  assert.equal(catalog.detailHtml({ id: { owner: "o", name: "n" }, type: "module" }, yanked, filters).includes("numan install "), false);
  const missingVersion = { version: "1.0.0", activation: { kind: "nu-module" }, artifact: { entry: "mod.nu" } };
  assert.ok(catalog.detailHtml({ id: { owner: "o", name: "n" }, type: "module" }, missingVersion, filters).includes("Lifecycle proof is missing"));
});

test("untrusted catalog text and links cannot inject markup or shell commands", () => {
  const p = { id: { owner: "owner", name: "bad;command" }, type: "script", description: '<img src=x onerror="alert(1)">', repo: "javascript:alert(1)", tags: ["<script>"], versions: [] };
  const v = { version: "1.0.0", artifact: { kind: "archive", url: 'https://example.com/" onclick="bad', sha256: "<unsafe>" }, evidence_tier: "provisional", deferral_reason: "<unsafe>", source: { git: "javascript:alert(1)", rev: "<unsafe>" }, proofs: [{ os: "<script>", arch: "x86_64", result: "passed" }] };
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
