"use client";

import { useUser } from "@clerk/nextjs";
import { useMutation } from "convex/react";
import { api } from "../../convex/_generated/api";
import { useEffect } from "react";

export function SyncUser() {
  const { user, isLoaded } = useUser();
  const getOrCreate = useMutation(api.users.getOrCreate);

  useEffect(() => {
    if (!isLoaded || !user) return;

    getOrCreate({
      clerkId: user.id,
      email: user.primaryEmailAddress?.emailAddress ?? "",
      name: user.fullName ?? user.firstName ?? "",
      imageUrl: user.imageUrl,
    });
  }, [isLoaded, user, getOrCreate]);

  return null;
}
