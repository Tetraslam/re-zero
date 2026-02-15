"use client";

import { useTheme } from "next-themes";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <button
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="text-xs text-muted-foreground hover:text-rem transition-colors"
    >
      {theme === "dark" ? "light" : "dark"}
    </button>
  );
}
