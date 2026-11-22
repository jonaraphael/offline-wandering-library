const missing = () => new DOMException("Missing entry", "NotFoundError");

export class Directory {
  kind = "directory";
  entries = new Map();
  constructor(name = "drive", options = {}) {
    this.name = name;
    this.options = options;
  }
  async getDirectoryHandle(name, {create = false} = {}) {
    if (!this.entries.has(name) && create) this.entries.set(name, new Directory(name, this.options));
    if (!this.entries.has(name)) throw missing();
    const handle = this.entries.get(name);
    if (handle.kind !== "directory") throw new DOMException("Wrong type", "TypeMismatchError");
    return handle;
  }
  async *values() { yield* this.entries.values(); }
  async getFileHandle(name, {create = false} = {}) {
    if (!this.entries.has(name) && create) this.entries.set(name, new FileHandle(name, this.options));
    if (!this.entries.has(name)) throw missing();
    const handle = this.entries.get(name);
    if (handle.kind !== "file") throw new DOMException("Wrong type", "TypeMismatchError");
    return handle;
  }
  async removeEntry(name) { if (!this.entries.delete(name)) throw missing(); }
  async file(path) {
    const names = path.split("/");
    const basename = names.pop();
    let directory = this;
    for (const name of names) directory = await directory.getDirectoryHandle(name);
    return directory.getFileHandle(basename);
  }
}

class FileHandle {
  kind = "file";
  bytes = new Blob([]);
  constructor(name, options) {
    this.name = name;
    this.options = options;
  }
  async getFile() { return this.bytes; }
  async createWritable({keepExistingData = false} = {}) {
    let swap = keepExistingData ? this.bytes : new Blob([]);
    let offset = 0;
    return {
      write: async contents => {
        this.options.beforeWrite?.(this.name, contents);
        const chunk = new Blob([contents]);
        const gap = offset > swap.size ? new Uint8Array(offset - swap.size) : new Uint8Array();
        swap = new Blob([swap.slice(0, offset), gap, chunk, swap.slice(offset + chunk.size)]);
        offset += chunk.size;
      },
      seek: async bytes => { offset = bytes; },
      truncate: async bytes => this.options.truncate?.(bytes),
      close: async () => { this.bytes = swap; },
      abort: async () => { this.options.onAbort?.(); }
    };
  }
}

