import { createHash, type Hash } from "node:crypto";

export class TeeHasher {
  private hash: Hash = createHash("sha256");

  update(chunk: Buffer): void {
    this.hash.update(chunk);
  }

  hexDigest(): string {
    return this.hash.copy().digest("hex");
  }
}

export async function hashChunks(chunks: AsyncIterable<Buffer>): Promise<string> {
  const hasher = new TeeHasher();
  for await (const chunk of chunks) {
    hasher.update(chunk);
  }
  return hasher.hexDigest();
}
