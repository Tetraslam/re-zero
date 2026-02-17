"use client";

import { useUser } from "@clerk/nextjs";
import { useMutation, useQuery } from "convex/react";
import { useTheme } from "next-themes";
import { api } from "../../convex/_generated/api";
import { useEffect } from "react";

export function SyncUser() {
  const { user, isLoaded } = useUser();
  const getOrCreate = useMutation(api.users.getOrCreate);
  const getOrCreateDefaultKey = useMutation(api.apiKeys.getOrCreateDefault);
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

  // Auto-generate default API key
  useEffect(() => {
    if (convexUser?._id) {
      getOrCreateDefaultKey({ userId: convexUser._id });
    }
  }, [convexUser?._id, getOrCreateDefaultKey]);

  // Apply saved theme preference
  useEffect(() => {
    if (convexUser?.theme) {
      setTheme(convexUser.theme);
    }
  }, [convexUser?.theme, setTheme]);

  return null;
}
