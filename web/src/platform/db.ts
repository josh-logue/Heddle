// Storage for drafts, backups and recent files, behind a small async interface so the
// logic using it (platform/safety.ts) runs in Node tests on a MemoryDb. The host supplies
// the real one (browserHost: IndexedDB; the desktop shell: files).

export const STORES = ["drafts", "backups", "files"] as const;
export type StoreName = (typeof STORES)[number];

export interface Db {
  get<T>(store: StoreName, key: string): Promise<T | undefined>;
  put(store: StoreName, key: string, value: unknown): Promise<void>;
  delete(store: StoreName, key: string): Promise<void>;
  /** Every [key, value] in a store. */
  all<T>(store: StoreName): Promise<[string, T][]>;
  /** Called before a draft or backup is written: a host whose storage can be cleared
   *  (a browser's, when space runs low) asks to keep it. */
  persist?(): void;
}

/** In memory: for tests, and when the browser has no usable IndexedDB (some private
 *  windows), so the app still runs, without anything surviving a reload. */
export class MemoryDb implements Db {
  private readonly data = new Map<StoreName, Map<string, unknown>>(STORES.map((s) => [s, new Map()]));
  async get<T>(store: StoreName, key: string): Promise<T | undefined> {
    return this.data.get(store)!.get(key) as T | undefined;
  }
  async put(store: StoreName, key: string, value: unknown): Promise<void> {
    this.data.get(store)!.set(key, value);
  }
  async delete(store: StoreName, key: string): Promise<void> {
    this.data.get(store)!.delete(key);
  }
  async all<T>(store: StoreName): Promise<[string, T][]> {
    return [...this.data.get(store)!] as [string, T][];
  }
}

/** A Db usable straight away while the real one is still opening: each call waits for it. */
export function laterDb(db: Promise<Db>): Db {
  return {
    get: async (store, key) => (await db).get(store, key),
    put: async (store, key, value) => (await db).put(store, key, value),
    delete: async (store, key) => (await db).delete(store, key),
    all: async (store) => (await db).all(store),
    persist: () => void db.then((d) => d.persist?.()),
  };
}
