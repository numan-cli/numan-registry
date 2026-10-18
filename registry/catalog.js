/* The catalog is display-only. Numan owns signature verification and installation. */
(function () {
  "use strict";

  var TYPES = ["plugin", "module", "script", "completion"];
  var LABELS = { plugin: "Plugins", module: "Modules", script: "Scripts", completion: "Completions" };
  var TARGETS = {
    "x86_64-pc-windows-msvc": "Windows · x64",
    "aarch64-pc-windows-msvc": "Windows · ARM64",
    "x86_64-apple-darwin": "macOS · Intel",
    "aarch64-apple-darwin": "macOS · Apple silicon",
    "x86_64-unknown-linux-gnu": "Linux · x64 (GNU target)",
    "aarch64-unknown-linux-gnu": "Linux · ARM64 (GNU target)"
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function safeUrl(value) {
    try {
      var url = new URL(value);
      return /^https?:$/.test(url.protocol) ? url.href : "";
    } catch (_) { return ""; }
  }

  function parseNu(version) {
    if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version)) return null;
    var parts = version.split(".").map(Number);
    return parts.every(Number.isSafeInteger) ? parts : null;
  }

  function compare(a, b) {
    for (var i = 0; i < 3; i++) {
      if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
    }
    return 0;
  }

  // Match the exact/comparator/minor-wildcard grammar in scripts/nu_version_constraint.py.
  // null means unknown, never a compatibility claim.
  function matchesNu(constraint, version) {
    var candidate = parseNu(version);
    if (!candidate || typeof constraint !== "string" || !constraint.trim()) return null;
    if (constraint.trim() === "*") return true;
    var results = constraint.trim().split(/\s+/).map(function (token) {
      var wild = token.match(/^=?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(?:x|X|\*)$/);
      if (wild) return candidate[0] === Number(wild[1]) && candidate[1] === Number(wild[2]);
      var match = token.match(/^(>=|<=|>|<|=)?(.+)$/);
      var required = match && parseNu(match[2]);
      if (!required) return null;
      var cmp = compare(candidate, required);
      return { ">=": cmp >= 0, "<=": cmp <= 0, ">": cmp > 0, "<": cmp < 0, "=": cmp === 0 }[match[1] || "="];
    });
    if (results.indexOf(null) !== -1) return null;
    return results.every(Boolean);
  }

  function latest(pkg) {
    // Intake append order is authoritative, including commit-snapshot suffixes.
    return pkg.versions[pkg.versions.length - 1] || {};
  }

  function binaryTargets(version) {
    return Object.keys((version.artifact || {}).targets || {}).sort();
  }

  function targetMatches(version, target) {
    if (!target) return true;
    var artifact = version.artifact || {};
    if (artifact.kind === "source") return false;
    var targets = binaryTargets(version);
    // An archive without target metadata is not proof of OS support.
    return targets.length ? targets.indexOf(target) !== -1 : artifact.kind === "archive";
  }

  function canActivate(pkg, version) {
    return pkg.type === "plugin" || (pkg.type === "module" && (version.activation || {}).kind === "nu-module" &&
      !!(version.artifact || {}).entry && Object.keys(version.dependencies || {}).length === 0 &&
      [undefined, "module", "all"].indexOf((version.activation || {}).import) !== -1);
  }

  function filterPackages(packages, filters) {
    var query = filters.q.toLowerCase().trim();
    return packages.filter(function (pkg) {
      var version = latest(pkg);
      var search = [pkg.id.owner + "/" + pkg.id.name, pkg.type, pkg.description, (pkg.tags || []).join(" "), version.version, version.nu_version].join(" ").toLowerCase();
      return (!filters.type || pkg.type === filters.type) && (!query || search.indexOf(query) !== -1) &&
        targetMatches(version, filters.target) && (!filters.only || !parseNu(filters.nu) || matchesNu(version.nu_version, filters.nu) === true);
    });
  }

  function compatibility(version, nu) {
    if (!nu || !parseNu(nu)) return "";
    var match = matchesNu(version.nu_version, nu);
    var message = match === null ? "Nu compatibility unknown" : match ? "Matches Nu " + nu : "Requires " + version.nu_version + "; excludes Nu " + nu;
    return '<span class="compatibility"' + (match === null ? "" : ' data-compatible="' + match + '"') + ">" + escapeHtml(message) + "</span>";
  }

  function targetSummary(version) {
    var targets = binaryTargets(version);
    if (targets.length) return targets.map(function (t) { return TARGETS[t] || t; }).join("; ");
    return (version.artifact || {}).kind === "archive" ? "Untargeted archive · check upstream OS requirements" : "No published binary targets";
  }

  function command(text) {
    return '<div class="command"><code>' + escapeHtml(text) + '</code><button class="plain-button" type="button" data-copy="' + escapeHtml(text) + '" aria-label="Copy ' + escapeHtml(text) + '">Copy</button></div>';
  }

  function packageHash(id, version) {
    var params = new URLSearchParams({ package: id });
    if (version) params.set("version", version);
    return "#" + params.toString();
  }

  function publicationHtml(metadata) {
    var built = new Date(metadata.built_at);
    if (["production", "staging"].indexOf(metadata.environment) === -1 || !/^[0-9a-f]{40}$/.test(metadata.source_revision) || isNaN(built.getTime())) return "";
      ' · source <a href="' + escapeHtml("https://github.com/numan-cli/numan-registry/commit/" + metadata.source_revision) + '">' + escapeHtml(metadata.source_revision.slice(0, 12)) + "</a>. Build time precedes deployment; this unsigned metadata is informational.";
      ' · source <a href="' + escapeHtml("https://github.com/numan-cli/numan-registry/commit/" + metadata.source_revision) + '">' + escapeHtml(metadata.source_revision.slice(0, 12)) + "</a>. Build time precedes deployment; this unsigned metadata is informational.";
  }

  function evidenceSummary(version, supported) {
    return version.evidence_tier === "provisional" ? "Provisional: " + (version.deferral_reason || "Lifecycle proof deferred") :
      (version.verified_with || []).length ? "Exact tested Nu versions are listed above. This is not an all-platform test guarantee." :
      supported ? "Lifecycle proof is missing. Production admission has not been established for this version." : "Install-only; no activation lifecycle proof is recorded.";
  }

  function artifactHtml(version) {
    var artifact = version.artifact || {};
    var targets = binaryTargets(version);
    var assets = targets.length ? targets.map(function (target) { return { target: target, asset: artifact.targets[target] }; }) : [{ target: "Archive", asset: artifact }];
    return assets.map(function (item) {
      var url = safeUrl(item.asset.url);
      return "<li>" + (url ? '<a href="' + escapeHtml(url) + '">' + escapeHtml(TARGETS[item.target] || item.target) + " artifact</a>" : escapeHtml(item.target) + ": no downloadable artifact") +
        (item.asset.sha256 ? "<br>SHA256: <code>" + escapeHtml(item.asset.sha256) + "</code>" : "") + "</li>";
    }).join("");
  }

  function installationHtml(id, version, supported) {
    var html = "";
    // Catalog values are displayed as text. Only safe package tokens become shell commands.
    if (/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(id) && /^[A-Za-z0-9_.+-]+$/.test(version.version || "")) {
      html += "<h3>Install this version</h3><p>After the initial setup above, inspect and install:</p>" +
        command("numan info " + id) + command("numan install " + id + "@" + version.version);
      if (supported) {
        html += "<p>Installation is inert. Register this package with Nushell explicitly:</p>" + command("numan activate " + id) +
          "<p>For modules, open a new Nu session to load the generated autoload. Follow upstream documentation for exported commands.</p>";
      } else {
        html += "<p>Install-only: this catalog version has no supported activation path. Numan does not execute it. Inspect the installed files with <code>numan list</code> and follow upstream usage instructions.</p>";
      }
    }
    return html;
  }

  function detailHtml(pkg, version, filters) {
    var id = pkg.id.owner + "/" + pkg.id.name;
    var repo = safeUrl(pkg.repo);
    var source = version.source || {};
    var tested = (version.verified_with || []).join(", ") || "No exact lifecycle-tested Nu versions recorded";
    var supported = canActivate(pkg, version);
    var evidence = evidenceSummary(version, supported);
    var assetHtml = artifactHtml(version);
    var html = '<div class="detail-heading"><h2 id="detail-title">' + escapeHtml(id) + '</h2><button class="plain-button" type="button" id="close-detail">Close details</button></div>' +
      "<p>" + escapeHtml(pkg.description) + '</p><p class="tags">' + escapeHtml((pkg.tags || []).join(" · ")) + '</p><div class="detail-actions">' +
      (repo ? '<a href="' + escapeHtml(repo) + '">Upstream documentation</a>' : "") +
      '<a href="' + escapeHtml(packageHash(id, version.version)) + '">Link to this version</a>' +
      '<button class="plain-button" type="button" data-copy="' + escapeHtml(id) + '">Copy package ID</button></div>' +
      '<p><label for="package-version">Catalog version </label><select id="package-version">' + pkg.versions.slice().reverse().map(function (v) {
        return '<option value="' + escapeHtml(v.version) + '"' + (v === version ? " selected" : "") + ">" + escapeHtml(v.version) + (v === latest(pkg) ? " (latest in catalog)" : "") + "</option>";
      }).join("") + "</select></p><dl><dt>Package type</dt><dd>" + escapeHtml(pkg.type) + (supported ? " · explicit activation supported" : " · install-only") + "</dd>" +
      "<dt>Declared Nu range</dt><dd><code>" + escapeHtml(version.nu_version || "Unknown") + "</code>" + compatibility(version, filters.nu) + "</dd>" +
      "<dt>Lifecycle-tested Nu</dt><dd>" + escapeHtml(tested) + "</dd><dt>Evidence</dt><dd>" + escapeHtml(evidence) + "</dd>" +
      "<dt>Published targets</dt><dd>" + escapeHtml(targetSummary(version)) +
      (filters.target && !targetMatches(version, filters.target) ? '<span class="compatibility" data-compatible="false">No binary published for your selected target</span>' : "") + "</dd>" +
      "<dt>Source revision</dt><dd>" + escapeHtml(source.rev || "Not recorded") + (version.provenance ? " · " + escapeHtml(version.provenance) : "") + "</dd></dl>";
    html += installationHtml(id, version, supported);
    html += '<details class="guide"><summary>Artifact hashes and provenance</summary><p>Numan verifies artifact hashes. A catalog signature authenticates the index publisher; it does not guarantee package safety.</p><ul>' + assetHtml + "</ul>";
    [source.git, source.upstream].forEach(function (value) {
      var url = safeUrl(value);
      if (url) html += '<p>Source: <a href="' + escapeHtml(url) + '">' + escapeHtml(url) + "</a></p>";
    });
    return html + "</details>";
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { parseNu: parseNu, matchesNu: matchesNu, latest: latest, targetMatches: targetMatches, canActivate: canActivate, filterPackages: filterPackages, detailHtml: detailHtml, safeUrl: safeUrl, packageHash: packageHash, publicationHtml: publicationHtml };
  }
  if (typeof document === "undefined") return;

  function el(id) { return document.getElementById(id); }
  var packages = [], activeType = "", collapsed = {}, selectedId = "", selectedVersion = "", toastTimer;
  var search = el("catalog-search"), nu = el("nu-filter"), target = el("target-filter"), only = el("compatible-only");
  var status = el("catalog-status"), detail = el("package-detail"), rows = el("package-rows");

  function filters() { return { q: search.value, type: activeType, nu: nu.value.trim(), target: target.value, only: only.checked }; }

  function readLocation() {
    var params = new URLSearchParams(window.location.search);
    search.value = params.get("q") || "";
    nu.value = params.get("nu") || "";
    activeType = TYPES.indexOf(params.get("type")) !== -1 ? params.get("type") : "";
    target.value = params.get("target") || "";
    only.checked = params.get("compatible") === "1";
    var hash = new URLSearchParams(window.location.hash.slice(1));
    selectedId = hash.get("package") || "";
    selectedVersion = hash.get("version") || "";
  }

  function saveLocation() {
    var params = new URLSearchParams(window.location.search);
    var values = { q: search.value, nu: nu.value.trim(), type: activeType, target: target.value, compatible: only.checked ? "1" : "" };
    Object.keys(values).forEach(function (key) { if (values[key]) params.set(key, values[key]); else params.delete(key); });
    var query = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (query ? "?" + query : "") + window.location.hash);
  }

  function renderDetail(focus) {
    detail.hidden = !selectedId;
    if (!selectedId) return;
    var pkg = packages.find(function (p) { return p.id.owner + "/" + p.id.name === selectedId; });
    if (!pkg) {
      detail.innerHTML = '<h2 id="detail-title">Package not found</h2><p>This package is not in the loaded catalog.</p><button class="plain-button" id="close-detail" type="button">Close details</button>';
    } else {
      var version = selectedVersion ? pkg.versions.find(function (v) { return v.version === selectedVersion; }) : latest(pkg);
      detail.innerHTML = version ? detailHtml(pkg, version, filters()) : '<h2 id="detail-title">Version not found</h2><p>The requested version is not in this catalog.</p><a href="' + escapeHtml(packageHash(selectedId)) + '">Open latest catalog version</a>';
    }
    if (focus) detail.focus();
  }

  function refresh() {
    var f = filters(), valid = !f.nu || !!parseNu(f.nu);
    nu.setAttribute("aria-invalid", valid ? "false" : "true");
    el("nu-error").hidden = valid;
    el("nu-error").textContent = valid ? "" : "Enter an exact Nu version such as 0.114.1. Nu matching is paused until this is corrected.";
    var visible = filterPackages(packages, f), html = [], lastType = "";
    visible.forEach(function (pkg) {
      var version = latest(pkg), id = pkg.id.owner + "/" + pkg.id.name;
      if (lastType !== pkg.type) {
        lastType = pkg.type;
        html.push('<tr class="group"><td colspan="4"><button type="button" data-group="' + escapeHtml(pkg.type) + '" aria-expanded="' + !collapsed[pkg.type] + '">' + (collapsed[pkg.type] ? "Show " : "Hide ") + escapeHtml(LABELS[pkg.type] || pkg.type) + "</button></td></tr>");
      }
      if (collapsed[pkg.type]) return;
      html.push('<tr class="pkg-row' + (valid && matchesNu(version.nu_version, f.nu) === true ? " is-match" : "") + '"><td class="pkg"><a href="' + escapeHtml(packageHash(id)) + '">' + escapeHtml(id) + '</a><div class="pkg-description">' + escapeHtml(pkg.description) + '</div></td><td class="type">' + escapeHtml(pkg.type) +
        (!canActivate(pkg, version) ? '<span class="target-summary">Install-only</span>' : "") + '</td><td class="ver">' + escapeHtml(version.version || "Unavailable") + '</td><td class="nu"><code>' + escapeHtml(version.nu_version || "Unknown") + "</code>" + compatibility(version, f.nu) + '<span class="target-summary">' + escapeHtml(targetSummary(version)) + "</span></td></tr>");
    });
    rows.innerHTML = html.join("");
    el("package-table").hidden = !visible.length;
    el("empty-state").hidden = !!visible.length;
    var count = packages.filter(function (p) { return p.type === "plugin"; }).length;
    status.textContent = "Showing " + visible.length + " of " + packages.length + " packages · " + count + " plugins · latest catalog versions" +
      (parseNu(f.nu) ? " · " + visible.filter(function (p) { return matchesNu(latest(p).nu_version, f.nu) === true; }).length + " match Nu " + f.nu : "") +
      (f.target ? " · includes untargeted archives; check upstream requirements" : "");
    Array.prototype.forEach.call(el("type-tabs").querySelectorAll("button"), function (button) { button.setAttribute("aria-pressed", button.dataset.type === activeType ? "true" : "false"); });
    renderDetail(false);
    saveLocation();
  }

  function reset() {
    search.value = ""; nu.value = ""; target.value = ""; only.checked = false; activeType = ""; collapsed = {};
    refresh(); search.focus();
  }

  function toast(text) {
    el("toast").textContent = text; el("toast").classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { el("toast").classList.remove("show"); }, 2500);
  }

  document.addEventListener("click", function (event) {
    var copy = event.target.closest("button[data-copy]");
    if (copy) {
      if (!navigator.clipboard || !navigator.clipboard.writeText) { toast("Copy unavailable. Select and copy the displayed text."); return; }
      navigator.clipboard.writeText(copy.dataset.copy).then(function () { toast("Copied " + copy.dataset.copy); }).catch(function () { toast("Copy unavailable. Select and copy the displayed text."); });
    }
    var group = event.target.closest("button[data-group]");
    if (group) {
      collapsed[group.dataset.group] = !collapsed[group.dataset.group]; refresh();
      rows.querySelector('button[data-group="' + group.dataset.group + '"]').focus();
    }
    if (event.target.id === "close-detail") {
      var previous = selectedId;
      selectedId = ""; selectedVersion = "";
      window.history.pushState(null, "", window.location.pathname + window.location.search + "#catalog");
      renderDetail(false);
      var link = Array.prototype.find.call(rows.querySelectorAll("a"), function (a) { return a.hash === packageHash(previous); });
      if (link) link.focus(); else search.focus();
    }
  });
  detail.addEventListener("change", function (event) {
    if (event.target.id === "package-version") window.location.hash = packageHash(selectedId, event.target.value);
  });
  el("type-tabs").addEventListener("click", function (event) {
    var button = event.target.closest("button[data-type]");
    if (button) { activeType = button.dataset.type; collapsed = {}; refresh(); }
  });
  [search, nu].forEach(function (input) { input.addEventListener("input", refresh); });
  [target, only].forEach(function (input) { input.addEventListener("change", refresh); });
  el("reset-filters").addEventListener("click", reset);
  el("empty-reset").addEventListener("click", reset);
  window.addEventListener("hashchange", function () { readLocation(); renderDetail(true); });
  window.addEventListener("popstate", function () { readLocation(); refresh(); });

  var metadataController = new AbortController();
  var metadataTimeout = setTimeout(function () { metadataController.abort(); }, 15000);
  fetch("./publication.json", { signal: metadataController.signal }).then(function (response) {
    if (!response.ok) throw new Error("No publication metadata");
    return response.json();
  }).then(function (metadata) {
    var html = publicationHtml(metadata);
    if (!html) throw new Error("Invalid publication metadata");
    el("publication-build").innerHTML = html;
  }).catch(function () {
    el("publication-build").textContent = "Publication build metadata unavailable (local preview or older publication). See production publication history below.";
  }).finally(function () { clearTimeout(metadataTimeout); });

  var controller = new AbortController();
  var timeout = setTimeout(function () { controller.abort(); }, 15000);
  fetch("./index.json", { credentials: "same-origin", signal: controller.signal }).then(function (response) {
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }).then(function (index) {
    if (index.schema_version !== 1 || !Array.isArray(index.packages)) throw new Error("Unsupported catalog format");
    packages = index.packages.slice().sort(function (a, b) {
      return TYPES.indexOf(a.type) - TYPES.indexOf(b.type) || (a.id.owner + "/" + a.id.name).localeCompare(b.id.owner + "/" + b.id.name);
    });
    var targets = new Set();
    packages.forEach(function (p) { p.versions.forEach(function (v) { binaryTargets(v).forEach(function (t) { targets.add(t); }); }); });
    Array.from(targets).sort().forEach(function (t) { var option = document.createElement("option"); option.value = t; option.textContent = TARGETS[t] || t; target.appendChild(option); });
    el("type-tabs").innerHTML = [{ type: "", label: "All" }].concat(TYPES.map(function (t) { return { type: t, label: LABELS[t] }; })).map(function (tab) {
      return '<button type="button" data-type="' + tab.type + '" aria-pressed="false">' + tab.label + "</button>";
    }).join("");
    readLocation();
    var updated = new Date(index.updated_at), age = Math.floor((Date.now() - updated.getTime()) / 86400000);
    el("publication-status").textContent = "Catalog updated " + (isNaN(age) ? "at an unavailable time" : updated.toISOString().slice(0, 10) + (age > 30 ? " (" + age + " days ago)" : "")) + ". See publication details below for source and build information.";
    el("catalog-controls").hidden = false;
    status.dataset.state = "ready";
    refresh();
    if (selectedId) renderDetail(true);
  }).catch(function (error) {
    console.error("Catalog load failed:", error);
    status.textContent = "Could not load the catalog. Reload to retry, or open raw index.json above.";
    status.dataset.state = "error";
    el("publication-status").textContent = "Catalog metadata unavailable. Check production publication history below.";
    el("catalog-controls").hidden = true;
  }).finally(function () { if (timeout !== null) clearTimeout(timeout); });
  }).finally(function () { clearTimeout(timeout); });
})();
