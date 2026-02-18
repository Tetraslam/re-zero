"use client";

import { useState, useEffect } from "react";

const SPINNER_FRAMES = ["|", "/", "—", "\\"];

export function RemSpinner() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % SPINNER_FRAMES.length), 120);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="inline-block w-3 text-center text-rem tabular-nums">
      {SPINNER_FRAMES[frame]}
    </span>
  );
}

export function RemLoader({ text = "Loading" }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <RemSpinner />
      <span>{text}</span>
    </div>
  );
}
