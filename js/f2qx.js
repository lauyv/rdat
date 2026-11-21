const source = ($resource.content || "").replace(/\r\n?/g, "\n");
function sectionLines(name) {
  const pattern = new RegExp("^\\s*\\[" + name + "\\][^\\S\\n]*$([\\s\\S]*?)(?=^[^\\S\\n]*\\[[\\w-]+\\][^\\S\\n]*$|(?![\\s\\S]))", "gim");
  return Array.from(source.matchAll(pattern), (match) => match[1]).join("\n").split("\n");
}
let content = sectionLines("server_local").map((line) => line.trim())
  .filter((line) => line && !/^(?:[;#]|\/\/)/.test(line)).join("\n");
for (const line of sectionLines("dns")) {
  const alias = line.match(/^\s*alias\s*=\s*\/([a-z0-9_.-]+)\/([a-z0-9_.-]+)\/?\s*(?:[;#].*)?$/i);
  if (alias) content = content.replaceAll(alias[1], alias[2]);
}
$done({ content });
