// Drafts, backups and recent files in IndexedDB (part of browserHost).

import { MemoryDb, STORES, type Db, type StoreName } from "../db.ts";

const DB_NAME = "heddle";
const DB_VERSION = 1;

function request<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

class IndexedDb implements Db {
  persist = askToPersist;

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

let askedToPersist = false;

/** Ask the browser, once, not to clear our storage when space runs low (it may still).
 *  Called when the first draft or backup is written, not on loading the page: Firefox
 *  asks the user, and the question only makes sense once there's something to keep. */
function askToPersist(): void {
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
