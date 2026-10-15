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

function convertBase64(source) {
  if (!/^\s*anytls:\/\//im.test(source)) {
    try {
      source = decodeBase64(source);
    } catch {
      return "";
    }
  }
  if (/\[server_local\]/i.test(source)) return convertFullCfg(source);
  const servers = [];
  for (const value of source.split(/\r?\n/)) {
    const line = value.trim();
    if (!/^anytls:\/\//i.test(line)) continue;
    try {
      // Parse manually: URL and URLSearchParams are not required in the QX runtime.
      const match = line.match(/^anytls:\/\/([^@]+)@(\[[^\]]+\]|[^:/?#\s]+):(\d+)\/?(?:\?([^#]*))?(?:#(.*))?$/i);
      if (!match || Number(match[3]) < 1 || Number(match[3]) > 65535) continue;
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
      if ([password, name, sni || ""].some((value) => /[,\r\n]/.test(value))) continue;
      const fields = ["anytls=" + host + ":" + match[3], "password=" + password, "over-tls=true"];
      if (sni) fields.push("tls-host=" + sni);
      const insecure = params.insecure !== undefined ? params.insecure : params.allowinsecure;
      if (insecure !== undefined) {
        if (!/^(?:0|1|true|false)$/i.test(insecure)) continue;
        fields.push("tls-verification=" + !/^(?:1|true)$/i.test(insecure));
      }
      if (params.udp !== undefined) {
        if (!/^(?:0|1|true|false)$/i.test(params.udp)) continue;
        fields.push("udp-relay=" + /^(?:1|true)$/i.test(params.udp));
      }
      fields.push("tag=" + name);
      servers.push(fields.join(", "));
    } catch {
      // Skip malformed nodes without discarding the subscription.
    }
  }
  return servers.join("\n");
}

function convertFullCfg(source) {
  const section = source.match(/\[server_local\]([\s\S]*?)(?=\r?\n\s*\[|$)/i)?.[1] || "";
  const servers = section.split(/\r?\n/).filter((line) => line.trim() && !/^\s*(?:[;#]|\/\/|anytls:\/\/)/i.test(line));
  if (/^\s*anytls:\/\//im.test(section)) {
    const converted = convertBase64(section);
    if (converted) servers.push(converted);
  }
  let content = servers.join("\n");
  const dns = source.match(/\[dns\]([\s\S]*?)(?=\r?\n\s*\[|$)/i)?.[1] || "";
  for (const line of dns.split(/\r?\n/)) {
    const alias = line.match(/^\s*alias\s*=\s*\/([a-z0-9_.-]+)\/([a-z0-9_.-]+)\/?\s*(?:[;#].*)?$/i);
    if (alias) content = content.replaceAll(alias[1], alias[2]);
  }
  return content;
}

const source = $resource.content || "";
const content = /\[server_local\]/i.test(source) ? convertFullCfg(source) : convertBase64(source);
$done({ content: content.replace(/((?:^|,)\s*tag\s*=)([^,\r\n]*)/gim, (_, prefix, name) => prefix + name.replaceAll("[A]", "")) });
