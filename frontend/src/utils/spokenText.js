export function speechChunks(markdown) {
  const text = String(markdown || '')
    .replace(/```[\s\S]*?```/g, '（代码示例请查看正文。）')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/^[\s#>*|\-]+/gm, '')
    .replace(/[`*_]/g, '')
    .replace(/https?:\/\/\S+/g, '')
    .trim()
  return text.match(/[^。！？\n]{1,150}[。！？\n]?/g)?.map(s => s.trim()).filter(Boolean) || []
}
