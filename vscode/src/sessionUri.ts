/** A session's resource identity; titles never participate in lookup or restoration. */
export function sessionResource(server: string, provider: string, id: string): string {
  const endpoint = server.replace(/\/+$/, "")
  return `ax-session:/${provider}/${`v1-${Buffer.from(id, "utf8").toString("base64url")}`}.axsession?server=${encodeURIComponent(endpoint)}`
}

export function readSessionResource(resource: string) {
  const uri = new URL(resource)
  const parts = uri.pathname.split("/")
  const provider = parts[1]
  const encoded = parts
    .slice(2)
    .join("/")
    .replace(/\.axsession$/, "")
  const id = encoded.startsWith("v1-")
    ? Buffer.from(encoded.slice(3), "base64url").toString("utf8")
    : decodeURIComponent(encoded)
  // VS Code's Uri serializer percent-encodes '=' and nested URL characters in
  // opaque queries. Accept that serialization as well as the original resource.
  const params = uri.searchParams.has("server")
    ? uri.searchParams
    : new URLSearchParams(decodeURIComponent(uri.search.slice(1)))
  const server = params.get("server")
  if ((provider !== "claude" && provider !== "codex") || !id || !server)
    throw new Error("Invalid ax session resource")
  return { provider, id, server } as { provider: "claude" | "codex"; id: string; server: string }
}
