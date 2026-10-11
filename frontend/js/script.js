const themeToggle = document.querySelector(".theme-toggle");

if (themeToggle) {
  const themeColor = document.querySelector('meta[name="theme-color"]');
  let isDark = false;

  try {
    isDark = localStorage.getItem("chatify-theme") === "dark";
  } catch {
    // The theme switch still works when browser storage is unavailable.
  }

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
