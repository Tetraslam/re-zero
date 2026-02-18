"use client";

import { AutumnProvider } from "autumn-js/react";
import { useAuth } from "@clerk/nextjs";

export function AutumnWrapper({ children }: { children: React.ReactNode }) {
  const { getToken } = useAuth();

  return (
    <AutumnProvider getBearerToken={() => getToken()} includeCredentials>
      {children}
    </AutumnProvider>
  );
}
