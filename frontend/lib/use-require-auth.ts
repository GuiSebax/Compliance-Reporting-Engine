"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "./auth-context";

/** Redirects to /login once we know (post-hydration) there is no token. */
export function useRequireAuth() {
  const { token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !token) {
      router.replace("/login");
    }
  }, [isLoading, token, router]);

  return { token, isReady: !isLoading && !!token };
}
