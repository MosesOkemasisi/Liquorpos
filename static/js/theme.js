/* Light / dark theme. Loaded in <head> so the right theme is applied before the page paints.
   Follows the computer's setting until the user picks one; the choice is remembered per browser. */
(function () {
  var KEY = "pos-theme";
  var root = document.documentElement;

  function read() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function write(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* private mode: just don't remember */ } }
  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function current() { return root.getAttribute("data-theme") || "dark"; }

  function paint() {
    var dark = current() === "dark";
    var label = dark ? "Switch to light mode" : "Switch to dark mode";
    document.querySelectorAll(".theme-icon").forEach(function (el) { el.textContent = dark ? "☀️" : "🌙"; });
    document.querySelectorAll(".theme-name").forEach(function (el) { el.textContent = label; });
    document.querySelectorAll("[data-theme-toggle]").forEach(function (el) {
      el.setAttribute("aria-label", label);
      el.setAttribute("title", label);
    });
  }

  var saved = read();
  root.setAttribute("data-theme", saved === "light" || saved === "dark" ? saved : systemTheme());

  document.addEventListener("click", function (e) {
    var toggle = e.target.closest && e.target.closest("[data-theme-toggle]");
    if (toggle) {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      write(next);
      paint();
      return;
    }
    // Clicking anywhere outside closes the profile menu.
    document.querySelectorAll("details.profile-menu[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.querySelectorAll("details.profile-menu[open]").forEach(function (d) { d.removeAttribute("open"); });
    }
  });

  document.addEventListener("DOMContentLoaded", paint);
})();
