"use client";

import { useTheme } from "next-themes";
import { useUser } from "@clerk/nextjs";
import { useMutation } from "convex/react";
import { api } from "../../convex/_generated/api";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const { user } = useUser();
  const updateTheme = useMutation(api.users.updateTheme);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (user) {
      updateTheme({ clerkId: user.id, theme: next });
    }
  };

  return (
    <button
      onClick={toggle}
      className="text-xs text-muted-foreground hover:text-rem transition-colors"
    >
      {theme === "dark" ? "light" : "dark"}
    </button>
  );
}
