(function () {
  var body = document.getElementById("rows");

  function fmt(iso) {
    if (!iso) return "never";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
  }

  function mark(connected) {
    if (connected === true) return '<span class="ok" title="Connected">✓</span>';
    if (connected === false) return '<span class="bad" title="Not connected">✕</span>';
    return '<span class="idle" title="Not checked yet">—</span>';
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&")
      .replace(/</g, "<")
      .replace(/>/g, ">")
      .replace(/"/g, """);
  }

  function paint(data) {
    var repos = (data && data.repos) || [];
    if (!repos.length) {
      body.innerHTML = '<tr><td colspan="4" class="empty">No subscribed repos.</td></tr>';
      return;
    }
    body.innerHTML = repos.map(function (r) {
      return (
        "<tr><td>" + esc(r.username) + "</td><td><a href=\"" + esc(r.url || "#") +
        "\">" + esc(r.repo) + "</a></td><td>" + esc(fmt(r.last_push)) +
        "</td><td class=\"status\">" + mark(r.connected) + "</td></tr>"
      );
    }).join("");
  }

  fetch("status.json?t=" + Date.now(), { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.json();
    })
    .then(paint)
    .catch(function () {
      body.innerHTML = '<tr><td colspan="4" class="empty">Could not read status.json.</td></tr>';
    });
})();
