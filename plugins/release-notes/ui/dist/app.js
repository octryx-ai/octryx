(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var T = {
    en: { pick: "Choose a version", none: "No versions found.", released: "Released", unreleased: "Not released",
          blockers: "Open blockers", noBlockers: "No open blockers.", open: "Still open", done: "Done",
          go: "Ready to ship", nogo: "Not ready", asOf: "as of", failed: "Could not read Jira: " }
  };
  function t(key) { return T.en[key]; }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function link(href, text) { var a = el("a", null, text); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; }
  function fail(error) {
    var box = $("error"); box.hidden = false;
    box.textContent = t("failed") + ((error && (error.message || error.code)) || "unknown error");
    window.octryx.resize();
  }
  function theme(ctx) {
    var tokens = (ctx.theme && ctx.theme.tokens) || {};
    Object.keys(tokens).forEach(function (k) { document.documentElement.style.setProperty("--" + k, tokens[k]); });
    if (ctx.theme && ctx.theme.mode) document.documentElement.dataset.theme = ctx.theme.mode;
  }
  function rows(result) { return (result && (result.versions || result.issues || result.tickets || result.results || result.items)) || []; }

  function loadVersions() {
    return window.octryx.call("list_jira_versions", {}).then(function (res) {
      var list = rows(res).slice().sort(function (a, b) { return (a.released === b.released) ? 0 : a.released ? 1 : -1; });
      var select = $("version"); select.textContent = "";
      if (!list.length) { select.appendChild(el("option", null, t("none"))); return; }
      select.appendChild(el("option", null, t("pick"))).value = "";
      list.forEach(function (v) {
        var o = el("option", null, (v.name || v.version) + (v.released ? " ✓" : ""));
        o.value = JSON.stringify({ name: v.name || v.version, product: v.product || v.project_key || v.projectKey || "" });
        select.appendChild(o);
      });
    });
  }

  function show(version, status, tickets) {
    var box = $("status"); box.textContent = ""; box.hidden = false;
    var blockers = (status && status.blockers) || [];
    var counts = (status && (status.issue_counts || status.counts)) || {};
    var openCount = (counts.to_do || 0) + (counts.in_progress || 0);
    var ready = !blockers.length && !openCount;
    var head = el("div", "verdict " + (ready ? "ok" : "bad"), ready ? t("go") : t("nogo"));
    box.appendChild(head);
    var meta = el("p", "muted small");
    meta.appendChild(document.createTextNode((status && status.released ? t("released") : t("unreleased"))
      + (status && status.release_date ? " · " + status.release_date : "")
      + (status && status.queried_at ? " · " + t("asOf") + " " + status.queried_at : "")));
    if (status && status.version_url) { meta.appendChild(document.createTextNode(" · ")); meta.appendChild(link(status.version_url, "Jira")); }
    box.appendChild(meta);
    var stats = el("div", "stats");
    [["done", counts.done || 0], ["open", openCount], ["blockers", blockers.length]].forEach(function (s) {
      var c = el("div", "stat"); c.appendChild(el("b", null, String(s[1]))); c.appendChild(el("span", null, t(s[0]))); stats.appendChild(c);
    });
    box.appendChild(stats);
    if (blockers.length) {
      box.appendChild(el("h2", null, t("blockers")));
      var ul = el("ul");
      blockers.forEach(function (b) { var li = el("li"); li.appendChild(b.url ? link(b.url, b.key || b.summary) : el("span", null, b.key)); li.appendChild(document.createTextNode(" " + (b.summary || ""))); ul.appendChild(li); });
      box.appendChild(ul);
    }
    var list = $("tickets"); list.textContent = ""; list.hidden = !tickets.length;
    if (tickets.length) {
      list.appendChild(el("h2", null, t("done") + " (" + tickets.length + ")"));
      var ul2 = el("ul");
      tickets.forEach(function (i) { var li = el("li"); li.appendChild(i.url ? link(i.url, i.key) : el("span", null, i.key)); li.appendChild(document.createTextNode(" " + (i.summary || i.title || ""))); ul2.appendChild(li); });
      list.appendChild(ul2);
    }
    window.octryx.resize();
  }

  $("pick").addEventListener("submit", function (event) {
    event.preventDefault();
    $("error").hidden = true;
    var raw = $("version").value; if (!raw) return;
    var v = JSON.parse(raw);
    Promise.all([
      window.octryx.call("jira_release_status", { product: v.product, version: v.name }).catch(function () { return null; }),
      window.octryx.call("search_jira_tickets", { jql: 'fixVersion = "' + v.name.replace(/"/g, '\\"') + '" AND statusCategory = Done ORDER BY key' })
    ]).then(function (res) { show(v.name, res[0], rows(res[1])); }, fail);
  });

  window.octryx.context().then(function (ctx) {
    document.documentElement.lang = "en";
    theme(ctx);
    return loadVersions();
  }).then(window.octryx.resize, fail);
})();
