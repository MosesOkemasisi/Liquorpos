/* Phone/tablet: the menu button (and the dark backdrop) open and close the side menu. */
document.addEventListener("click", function (e) {
  if (e.target.closest && e.target.closest("[data-nav-toggle]")) {
    document.body.classList.toggle("nav-open");
  }
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") document.body.classList.remove("nav-open");
});
