(() => {
  const storageKey = "wetbulb-theme";
  let theme = "dark";
  try {
    theme = localStorage.getItem(storageKey) === "light" ? "light" : "dark";
  } catch {}
  document.documentElement.dataset.theme = theme;

  const addToggle = () => {
    const host = document.querySelector(".controls") || document.querySelector("header.top");
    if (!host || document.getElementById("themeToggle")) return;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "theme-toggle";
    button.id = "themeToggle";
    button.addEventListener("click", () => {
      theme = theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = theme;
      button.innerHTML = theme === "dark" ? "<span aria-hidden=\"true\">☀</span> Light mode" : "<span aria-hidden=\"true\">☾</span> Dark mode";
      button.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} mode`);
      try { localStorage.setItem(storageKey, theme); } catch {}
      document.dispatchEvent(new CustomEvent("wetbulb:themechange", { detail: { theme } }));
    });
    button.innerHTML = theme === "dark" ? "<span aria-hidden=\"true\">☀</span> Light mode" : "<span aria-hidden=\"true\">☾</span> Dark mode";
    button.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} mode`);
    host.append(button);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", addToggle, { once: true });
  } else {
    addToggle();
  }
})();
