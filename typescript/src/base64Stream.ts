export async function encodeChunksToBase64(chunks: AsyncIterable<Buffer>): Promise<string> {
  const parts: string[] = [];
  let remainder = Buffer.alloc(0);

  for await (const chunk of chunks) {
    const buffer = Buffer.concat([remainder, chunk]);
    const usableLength = Math.floor(buffer.length / 3) * 3;
    const usable = buffer.subarray(0, usableLength);
    remainder = buffer.subarray(usableLength);
    if (usable.length > 0) {
      parts.push(usable.toString("base64"));
    }
  }

  if (remainder.length > 0) {
    parts.push(remainder.toString("base64"));
  }

  return parts.join("");
}
