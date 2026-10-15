const source = $resource.content || "";
const section = source.match(/\[server_local\]([\s\S]*?)(?=\r?\n\s*\[|$)/i)?.[1] || "";
let content = section.split(/\r?\n/).filter((line) => line.trim() && !/^\s*(?:[;#]|\/\/)/.test(line)).join("\n");
const dns = source.match(/\[dns\]([\s\S]*?)(?=\r?\n\s*\[|$)/i)?.[1] || "";
for (const line of dns.split(/\r?\n/)) {
  const alias = line.match(/^\s*alias\s*=\s*\/([a-z0-9_.-]+)\/([a-z0-9_.-]+)\/?\s*(?:[;#].*)?$/i);
  if (alias) content = content.replaceAll(alias[1], alias[2]);
}
$done({ content });
