// Shared theme selection for both the mixer and local pywebview loading page.
const AVAILABLE_THEMES = [];
function setMixerTheme(name) {
  if (typeof name !== "string" || !/^[a-zA-Z0-9_-]+$/.test(name)) name = "dark";
  const link = document.getElementById("themeStylesheet");
  if (link) {
    const localTheme = new URLSearchParams(location.search).get("local_theme_url");
    link.href = localTheme && location.protocol === "file:" ? localTheme : link.dataset.base + name + ".css";
  }
  document.documentElement.dataset.theme = name;
  try { localStorage.setItem("ffado-theme", name); } catch (_) {}
  return name;
}
// The loading screen uses a file:// URL with a theme query parameter.
const requestedTheme = new URLSearchParams(location.search).get("theme");
let savedTheme = "dark";
try { savedTheme = localStorage.getItem("ffado-theme") || "dark"; } catch (_) {}
setMixerTheme(requestedTheme || savedTheme);

// Accent overrides are applied after the theme stylesheet. A null value restores its default.
function setMixerAccent(color) {
  const valid = typeof color === "string" && /^#[0-9a-fA-F]{6}$/.test(color);
  document.documentElement.style.setProperty("--accent-color", valid ? color : "");
  document.documentElement.style.setProperty("--pin-color", valid ? color : "");
}
