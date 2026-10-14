// Quantumult X resource parser: full QX configs and Shadowrocket AnyTLS subscriptions.
function decodeBase64(value) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const input = value.replace(/\s/g, "").replace(/-/g, "+").replace(/_/g, "/");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(input) || input.replace(/=+$/, "").length % 4 === 1) {
    throw new Error("Invalid Base64 subscription");
  }
  let bits = 0;
  let buffer = 0;
  let encoded = "";
  for (const char of input.replace(/=+$/, "")) {
    buffer = (buffer << 6) | alphabet.indexOf(char);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      encoded += "%" + ((buffer >> bits) & 255).toString(16).padStart(2, "0");
    }
  }
  return decodeURIComponent(encoded);
}

function convertAnyTLS(line) {
  // Parse manually: URL and URLSearchParams are not required in the QX runtime.
  const match = line.match(/^anytls:\/\/([^@]+)@(\[[^\]]+\]|[^:/?#\s]+):(\d+)\/?(?:\?([^#]*))?(?:#(.*))?$/i);
  if (!match || Number(match[3]) < 1 || Number(match[3]) > 65535) return "";
  const password = decodeURIComponent(match[1]);
  const params = Object.create(null);
  for (const pair of (match[4] || "").split("&")) {
    if (!pair) continue;
    const index = pair.indexOf("=");
    const key = decodeURIComponent(index < 0 ? pair : pair.slice(0, index)).toLowerCase();
    params[key] = decodeURIComponent(index < 0 ? "" : pair.slice(index + 1));
  }
  const host = match[2];
  const name = match[5] ? decodeURIComponent(match[5]) : host + ":" + match[3];
  const sni = params.peer || params.sni;
  // Commas and newlines cannot be represented safely in QX server fields.
  if ([password, name, sni || ""].some((value) => /[,\r\n]/.test(value))) return "";
  const fields = ["anytls=" + host + ":" + match[3], "password=" + password, "over-tls=true"];
  if (sni) fields.push("tls-host=" + sni);
  const insecure = params.insecure !== undefined ? params.insecure : params.allowinsecure;
  if (insecure !== undefined) {
    if (!/^(?:0|1|true|false)$/i.test(insecure)) return "";
    fields.push("tls-verification=" + !/^(?:1|true)$/i.test(insecure));
  }
  if (params.udp !== undefined) {
    if (!/^(?:0|1|true|false)$/i.test(params.udp)) return "";
    fields.push("udp-relay=" + /^(?:1|true)$/i.test(params.udp));
  }
  fields.push("tag=" + name);
  return fields.join(", ");
}

let source = $resource.content || "";
if (!/\[server_local\]|^\s*anytls:\/\//im.test(source)) {
  try {
    source = decodeBase64(source);
  } catch {
    source = "";
  }
}

const section = source.match(/\[server_local\]([\s\S]*?)(?=\r?\n\s*\[|$)/i)?.[1] || "";
const tagged = /(?:^|,)\s*tag\s*=[^,]*(?:\uD83C[\uDDE6-\uDDFF]){2}/i;
const servers = section.split(/\r?\n/).filter((line) => !/^\s*[;#]/.test(line) && tagged.test(line));
// For full configs, only read server_local; do not consume links in other sections.
for (const line of (section || (/\[server_local\]/i.test(source) ? "" : source)).split(/\r?\n/)) {
  if (!/^\s*anytls:\/\//i.test(line)) continue;
  try {
    const converted = convertAnyTLS(line.trim());
    if (converted) servers.push(converted);
  } catch {
    // A malformed node must not prevent the remaining subscription from loading.
  }
}
$done({ content: servers.map((line) => line.replace(/((?:^|,)\s*tag\s*=)([^,]*)/i, (_, prefix, name) => prefix + name.replaceAll("[A]", ""))).join("\n") });
