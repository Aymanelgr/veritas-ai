import { useEffect, useState } from "react";

// "system" follows the OS setting; "light" / "dark" force a theme via <html data-theme>.
const KEY = "veritas-theme";
export const THEMES = ["system", "light", "dark"];

function stored() {
  try {
    return localStorage.getItem(KEY) ?? "system";
  } catch {
    return "system"; // storage can be blocked (private mode); fall back quietly
  }
}

export function useTheme() {
  const [theme, setTheme] = useState(stored);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* not critical */
    }
  }, [theme]);
  const next = () => setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]);
  return { theme, next };
}
