// Browser storage for drafts, backups and recent files: IndexedDB, behind a small async
// interface so the logic using it (platform/safety.ts) runs in Node tests on a MemoryDb.
// W9's desktop shell can supply a version that keeps them as files instead.

export const STORES = ["drafts", "backups", "files"] as const;
export type StoreName = (typeof STORES)[number];

export interface Db {
  get<T>(store: StoreName, key: string): Promise<T | undefined>;
  put(store: StoreName, key: string, value: unknown): Promise<void>;
  delete(store: StoreName, key: string): Promise<void>;
  /** Every [key, value] in a store. */
  all<T>(store: StoreName): Promise<[string, T][]>;
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

const DB_NAME = "heddle";
const DB_VERSION = 1;

function request<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

class IndexedDb implements Db {
  constructor(private readonly db: IDBDatabase) {}

  private async run<T>(store: StoreName, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
    const tx = this.db.transaction(store, mode);
    const result = await request(fn(tx.objectStore(store)));
    if (mode === "readwrite") {
      await new Promise<void>((resolve, reject) => {
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
      });
    }
    return result;
  }

  get<T>(store: StoreName, key: string): Promise<T | undefined> {
    return this.run(store, "readonly", (s) => s.get(key) as IDBRequest<T | undefined>);
  }
  async put(store: StoreName, key: string, value: unknown): Promise<void> {
    await this.run(store, "readwrite", (s) => s.put(value, key));
  }
  async delete(store: StoreName, key: string): Promise<void> {
    await this.run(store, "readwrite", (s) => s.delete(key));
  }
  async all<T>(store: StoreName): Promise<[string, T][]> {
    const [keys, values] = await Promise.all([
      this.run(store, "readonly", (s) => s.getAllKeys()),
      this.run(store, "readonly", (s) => s.getAll() as IDBRequest<T[]>),
    ]);
    return keys.map((k, i) => [String(k), values[i]!]);
  }
}

/** A Db usable straight away while the real one is still opening: each call waits for it. */
export function laterDb(db: Promise<Db>): Db {
  return {
    get: async (store, key) => (await db).get(store, key),
    put: async (store, key, value) => (await db).put(store, key, value),
    delete: async (store, key) => (await db).delete(store, key),
    all: async (store) => (await db).all(store),
  };
}

let askedToPersist = false;

/** Ask the browser, once, not to clear our storage when space runs low (it may still).
 *  Called when the first draft or backup is written, not on loading the page: Firefox
 *  asks the user, and the question only makes sense once there's something to keep. */
export function askToPersist(): void {
  if (askedToPersist || typeof navigator === "undefined") return;
  askedToPersist = true;
  void navigator.storage?.persist?.().catch(() => false);
}

/** The app's database: IndexedDB where it works, else in memory. */
export async function openDb(): Promise<Db> {
  try {
    const open = indexedDB.open(DB_NAME, DB_VERSION);
    open.onupgradeneeded = () => {
      for (const s of STORES) if (!open.result.objectStoreNames.contains(s)) open.result.createObjectStore(s);
    };
    return new IndexedDb(await request(open));
  } catch {
    return new MemoryDb();
  }
}
