"use client";

import { useUser } from "@clerk/nextjs";
import { useMutation, useQuery } from "convex/react";
import { useTheme } from "next-themes";
import { api } from "../../convex/_generated/api";
import { useEffect } from "react";

export function SyncUser() {
  const { user, isLoaded } = useUser();
  const getOrCreate = useMutation(api.users.getOrCreate);
  const { setTheme } = useTheme();

  const convexUser = useQuery(
    api.users.getByClerkId,
    isLoaded && user ? { clerkId: user.id } : "skip"
  );

  useEffect(() => {
    if (!isLoaded || !user) return;

    getOrCreate({
      clerkId: user.id,
      email: user.primaryEmailAddress?.emailAddress ?? "",
      name: user.fullName ?? user.firstName ?? "",
      imageUrl: user.imageUrl,
    });
  }, [isLoaded, user, getOrCreate]);

  // Apply saved theme preference
  useEffect(() => {
    if (convexUser?.theme) {
      setTheme(convexUser.theme);
    }
  }, [convexUser?.theme, setTheme]);

  return null;
}
