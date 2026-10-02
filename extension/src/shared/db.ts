/** 快照分片存储（扩展域 IndexedDB；大对象不经 chrome.storage / 消息直传）。 */

const DB_NAME = "sb-capture";
const STORE = "snapshot-parts";
const DB_VERSION = 1;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: ["captureId", "index"] });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(STORE, mode);
        const request = run(transaction.objectStore(STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        transaction.oncomplete = () => db.close();
      })
  );
}

export async function putSnapshotPart(
  captureId: string,
  index: number,
  data: ArrayBuffer
): Promise<void> {
  await tx("readwrite", (store) => store.put({ captureId, index, data }));
}

export async function countSnapshotParts(captureId: string): Promise<number> {
  return tx<number>(
    "readonly",
    (store) => store.count(IDBKeyRange.bound([captureId, -Infinity], [captureId, Infinity]))
  );
}

export async function hasSnapshotParts(captureId: string): Promise<boolean> {
  return (await countSnapshotParts(captureId)) > 0;
}

export async function getSnapshotParts(captureId: string): Promise<ArrayBuffer[]> {
  const rows = await tx<Array<{ index: number; data: ArrayBuffer }>>(
    "readonly",
    (store) => store.getAll(IDBKeyRange.bound([captureId, -Infinity], [captureId, Infinity]))
  );
  return rows.sort((a, b) => a.index - b.index).map((row) => row.data);
}

export async function deleteSnapshotParts(captureId: string): Promise<void> {
  await tx("readwrite", (store) =>
    store.delete(IDBKeyRange.bound([captureId, -Infinity], [captureId, Infinity]))
  );
}
