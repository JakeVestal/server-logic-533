(function () {
  var style = document.createElement("style");
  style.textContent = [
    ".site-bar {",
    "  display: flex;",
    "  gap: 18px;",
    "  align-items: center;",
    "  background: #040814;",
    "  border-bottom: 1px solid #1a3a66;",
    "  padding: 8px 28px;",
    "  font-family: Consolas, \"Cascadia Code\", \"Courier New\", monospace;",
    "  font-size: 12px;",
    "}",
    ".site-bar a { color: #8aa0c4; text-decoration: none; }",
    ".site-bar a:hover { color: #e8eefc; }",
    ".site-bar a.here { color: #7cff55; }",
    ".site-bar a.repo { margin-left: auto; color: #d4a017; }",
  ].join("\n");
  document.head.appendChild(style);

  var path = location.pathname.split("/").pop() || "index.html";
  function item(href, label) {
    var here = path === href || (path === "" && href === "index.html");
    return '<a href="' + href + '"' + (here ? ' class="here"' : "") + ">" + label + "</a>";
  }
  var bar = document.createElement("div");
  bar.className = "site-bar";
  bar.innerHTML =
    item("index.html", "Dashboard") +
    item("order.html", "Order menu") +
    item("setup.html", "Setup") +
    item("oi-clusters.html", "OI clusters") +
    '<a class="repo" href="https://github.com/JakeVestal/server-logic-533">GitHub repo</a>';
  var page = document.querySelector(".page");
  if (page) page.insertBefore(bar, page.firstChild);
  else document.body.insertBefore(bar, document.body.firstChild);
})();
