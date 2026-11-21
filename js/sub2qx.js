function sectionLines(source, name) {
  const pattern = new RegExp("^\\s*\\[" + name + "\\][^\\S\\n]*$([\\s\\S]*?)(?=^[^\\S\\n]*\\[[\\w-]+\\][^\\S\\n]*$|(?![\\s\\S]))", "gim");
  const sections = Array.from(source.matchAll(pattern), (match) => match[1]);
  return sections.length ? sections.join("\n").split("\n") : null;
}
function extractLocalNodes(source) {
  source = source.replace(/\r\n?/g, "\n");
  const nodes = sectionLines(source, "server_local");
  if (!nodes) return null;
  let content = nodes.map((line) => line.trim())
    .filter((line) => line && !/^(?:[;#]|\/\/)/.test(line)).join("\n");
  for (const line of sectionLines(source, "dns") || []) {
    const alias = line.match(/^\s*alias\s*=\s*\/([a-z0-9_.-]+)\/([a-z0-9_.-]+)\/?\s*(?:[;#].*)?$/i);
    if (alias) content = content.replaceAll(alias[1], alias[2]);
  }
  return content;
}
function decodeSubscription(source) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const base64 = source.replace(/\s/g, "").replace(/-/g, "+").replace(/_/g, "/");
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(base64)) return "";
  const data = base64.replace(/=+$/, "");
  if (data.length % 4 === 1 || (data !== base64 && base64.length % 4 !== 0)) return "";
  let buffer = 0;
  let bits = 0;
  let bytes = "";
  for (const char of data) {
    buffer = (buffer << 6) | alphabet.indexOf(char);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes += "%" + ((buffer >> bits) & 255).toString(16).padStart(2, "0");
    }
  }
  try {
    return decodeURIComponent(bytes);
  } catch {
    return "";
  }
}
function convertAnyTLS(line) {
  const match = line.match(
    /^anytls:\/\/([^@]+)@(\[[^\]]+\]|[^:/?#\s]+):(\d+)\/?(?:\?([^#]*))?(?:#(.*))?$/i,
  );
  if (!match) return "";
  const [, credentials, host, port, query = "", fragment] = match;
  if (Number(port) < 1 || Number(port) > 65535) return "";
  try {
    const params = new Map();
    for (const pair of query.split("&")) {
      const [key, ...value] = pair.split("=");
      params.set(decodeURIComponent(key).toLowerCase(), decodeURIComponent(value.join("=")));
    }
    const password = decodeURIComponent(credentials);
    const endpoint = host + ":" + port;
    const name = fragment ? decodeURIComponent(fragment) : endpoint;
    const sni = params.get("peer") || params.get("sni");
    if ([password, name, sni || ""].some((value) => /[,\r\n]/.test(value))) return "";
    const fields = ["anytls=" + endpoint, "password=" + password, "over-tls=true"];
    if (sni) fields.push("tls-host=" + sni);
    const insecure = params.get("insecure") ?? params.get("allowinsecure");
    const udp = params.get("udp");
    if (insecure !== undefined) {
      if (!/^(?:0|1|true|false)$/i.test(insecure)) return "";
      fields.push("tls-verification=" + !/^(?:1|true)$/i.test(insecure));
    }
    if (udp !== undefined) {
      if (!/^(?:0|1|true|false)$/i.test(udp)) return "";
      fields.push("udp-relay=" + /^(?:1|true)$/i.test(udp));
    }
    return fields.concat("tag=" + name).join(", ");
  } catch {
    return "";
  }
}
function parseSubscription(source) {
  const nodes = [];
  for (const raw of source.split(/\r\n?|\n/)) {
    const line = raw.trim();
    if (/^anytls:\/\//i.test(line)) {
      const node = convertAnyTLS(line);
      if (node) nodes.push(node);
    } else if (
      /^[a-z][\w+.-]*:\/\/\S+$/i.test(line) ||
      /^[a-z][\w-]*\s*=\s*[^,]+,.*\btag\s*=/i.test(line)
    ) {
      nodes.push(line);
    }
  }
  return nodes.join("\n");
}
function parseResource(source) {
  const nodes = extractLocalNodes(source);
  if (nodes !== null) return nodes;
  const decoded = decodeSubscription(source);
  return decoded ? extractLocalNodes(decoded) ?? parseSubscription(decoded) : parseSubscription(source);
}
$done({ content: parseResource($resource.content || "") });
