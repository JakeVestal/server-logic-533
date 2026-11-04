(function () {
  var badge = document.getElementById("badge");
  var priceBadge = document.getElementById("price-badge");
  var asof = document.getElementById("asof");
  var body = document.getElementById("rows");

  function setBadge(kind, text) {
    badge.className = "badge " + kind;
    badge.textContent = text;
  }

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

  function setPrice(kind, text) {
    if (!priceBadge) return;
    priceBadge.className = "badge " + kind;
    priceBadge.textContent = text;
  }

  function paint(data) {
    var probed = data && data.probed_at;
    if (!probed) {
      setBadge("idle", "not probed yet");
      asof.textContent = "The status file is a placeholder. Run the Luffy status workflow once.";
    } else if (!data.ok) {
      setBadge("bad", "probe failed");
      asof.textContent = "Last attempt " + fmt(probed);
    } else {
      var ageMin = (Date.now() - new Date(probed).getTime()) / 60000;
      if (ageMin > 120) setBadge("bad", "Luffy silent");
      else if (ageMin > 40) setBadge("stale", "status is stale");
      else setBadge("ok", "Luffy answering");
      asof.textContent = "Probed " + fmt(probed);
    }

    var run = data && data.price_run;
    if (!run || !run.finished_at) {
      setPrice("idle", "no price run yet");
    } else if (run.ok) {
      setPrice("ok", "price run ok");
      asof.textContent += " · Robin " + (run.bars_upserted || 0) +
        " bars, " + (run.repos_pushed || 0) + " repo(s) pushed " +
        fmt(run.finished_at);
    } else {
      setPrice("bad", "price run failed");
      asof.textContent += " · " + (run.error || "price run failed") +
        " (" + fmt(run.finished_at) + ")";
    }

    var repos = (data && data.repos) || [];
    if (!repos.length) {
      body.innerHTML = '<tr><td colspan="3" class="empty">No subscribed repos.</td></tr>';
      return;
    }
    body.innerHTML = repos.map(function (r) {
      var user = r.username || "";
      var name = r.repo || "";
      var href = r.url || "#";
      return (
        "<tr><td>" + esc(user) + "</td><td><a href=\"" + esc(href) + "\">" +
        esc(name) + "</a></td><td>" + esc(fmt(r.last_push)) + "</td></tr>"
      );
    }).join("");
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  fetch("status.json?t=" + Date.now(), { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.json();
    })
    .then(paint)
    .catch(function () {
      setBadge("bad", "no status file");
      asof.textContent = "Could not read status.json.";
      body.innerHTML = '<tr><td colspan="3" class="empty">Nothing to show.</td></tr>';
    });
})();
