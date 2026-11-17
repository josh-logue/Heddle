// Which tab holds what: the browser's Web Locks (part of browserHost).

import type { Locks } from "../safety.ts";

type LockManager = {
  request(name: string, options: { mode: "shared" | "exclusive" }, cb: () => Promise<void>): Promise<void>;
  query(): Promise<{ held?: { name?: string }[] }>;
};

/** The browser's Web Locks, or none (then nothing counts as held). */
export function browserLocks(): Locks {
  const locks = (navigator as Navigator & { locks?: LockManager }).locks;
  if (!locks) return { hold: async () => () => {}, held: async () => false };
  return {
    hold: (name, shared = false) => new Promise((acquired) => {
      void locks.request(name, { mode: shared ? "shared" : "exclusive" }, () => new Promise<void>((release) => acquired(release)));
    }),
    held: async (name) => ((await locks.query()).held ?? []).some((l) => l.name === name),
  };
}
