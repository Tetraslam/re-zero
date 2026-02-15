import { useEffect, useState } from "react";

/**
 * Ensures loading screens show for at least this many ms
 * so the Rem gif is actually visible. Change this one number.
 */
const MIN_LOADING_MS = 1000;

export function useMinLoading() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setReady(true), MIN_LOADING_MS);
    return () => clearTimeout(t);
  }, []);
  return ready;
}
