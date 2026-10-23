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
  updateAppIcon();
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
  updateAppIcon();
}
// file:// splash screens cannot fetch /api/settings. The desktop launcher
// supplies the saved theme and accent before FFADO or Flask is ready.
if (location.protocol === "file:") {
  const accent = new URLSearchParams(location.search).get("accent");
  if (accent) setMixerAccent(accent);
}

// The favicon and native window use the same logo as the themed intro.
// The browser's theme may differ from another browser window's theme.
function updateAppIcon() {
  const theme = document.documentElement.dataset.theme || "dark";
  const override = document.documentElement.style.getPropertyValue("--accent-color").trim();
  const query = new URLSearchParams({theme});
  if (/^#[0-9a-fA-F]{6}$/.test(override)) query.set("accent", override);
  const icon = document.querySelector('link[rel="icon"]');
  if (icon) {
    if (location.protocol === "file:") {
      const fileIcon = new URLSearchParams(location.search).get("icon_url");
      if (fileIcon) icon.href = fileIcon;
    } else {
      icon.href = "/favicon.svg?" + query.toString();
    }
  }
  // In a standalone browser there is no pywebview bridge: favicon only.
  const bridge = window.pywebview?.api;
  if (bridge?.set_theme_icon) {
    Promise.resolve(bridge.set_theme_icon(theme, override || null)).catch(() => {});
  }
}
window.addEventListener("pywebviewready", updateAppIcon);
