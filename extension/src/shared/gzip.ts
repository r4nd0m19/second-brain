/** gzip 压缩（CompressionStream）：快照在扩展端压缩后再传输（R1 体积治理）。 */

export async function gzipString(text: string): Promise<Uint8Array> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
