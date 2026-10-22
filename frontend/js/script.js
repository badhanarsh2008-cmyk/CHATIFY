const themeToggle = document.querySelector(".theme-toggle");

let savedDarkTheme = false;
try {
  savedDarkTheme = localStorage.getItem("chatify-theme") === "dark";
} catch {
  // Use the light theme when browser storage is unavailable.
}
document.body.classList.toggle("dark-theme", savedDarkTheme);

if (themeToggle) {
  const themeColor = document.querySelector('meta[name="theme-color"]');
  let isDark = savedDarkTheme;

  const applyTheme = (dark, save = false) => {
    document.body.classList.toggle("dark-theme", dark);
    themeToggle.setAttribute("aria-checked", String(dark));
    themeToggle.setAttribute(
      "aria-label",
      dark ? "Switch to light theme" : "Switch to dark theme",
    );
    themeToggle.title = dark ? "Switch to light theme" : "Switch to dark theme";

    if (themeColor) {
      themeColor.content = dark ? "#12242a" : "#f8fbfa";
    }

    if (save) {
      try {
        localStorage.setItem("chatify-theme", dark ? "dark" : "light");
      } catch {
        // Keep the current theme for this page view if storage is unavailable.
      }
    }
  };

  applyTheme(isDark);
  themeToggle.addEventListener("click", () => {
    isDark = themeToggle.getAttribute("aria-checked") !== "true";
    if (document.startViewTransition) {
      document.startViewTransition(() => applyTheme(isDark, true));
    } else {
      applyTheme(isDark, true);
    }
  });
}

const pageRoot = document.documentElement;

window.addEventListener("pageshow", (event) => {
  pageRoot.classList.remove("page-leaving");

  if (event.persisted) {
    pageRoot.classList.remove("page-ready");
    requestAnimationFrame(() => pageRoot.classList.add("page-ready"));
  } else {
    pageRoot.classList.add("page-ready");
  }
});

document.addEventListener("click", (event) => {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }

  const link = event.target.closest("a[href]");
  if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) {
    return;
  }

  const destination = new URL(link.href, window.location.href);
  if (
    destination.origin !== window.location.origin ||
    !["http:", "https:"].includes(destination.protocol) ||
    (destination.pathname === window.location.pathname && destination.search === window.location.search)
  ) {
    return;
  }

  event.preventDefault();
  pageRoot.classList.remove("page-ready");
  pageRoot.classList.add("page-leaving");
  window.setTimeout(() => window.location.assign(destination.href), 850);
});
