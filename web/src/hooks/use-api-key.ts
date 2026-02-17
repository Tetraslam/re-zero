"use client";

import { useMutation } from "convex/react";
import { useEffect, useState } from "react";
import { api } from "../../convex/_generated/api";
import { useCurrentUser } from "./use-current-user";

export function useApiKey() {
  const { user } = useCurrentUser();
  const getOrCreateDefault = useMutation(api.apiKeys.getOrCreateDefault);
  const [apiKey, setApiKey] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    getOrCreateDefault({ userId: user._id }).then(setApiKey);
  }, [user?._id]);

  return apiKey;
}
