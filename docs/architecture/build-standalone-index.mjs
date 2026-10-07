import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const architectureDirectory = resolve(import.meta.dirname)
const outputPath = process.argv[2]

if (!outputPath) {
  throw new Error('Usage: node build-standalone-index.mjs <output.html>')
}

const source = await readFile(resolve(architectureDirectory, 'index.html'), 'utf8')
const links = [...source.matchAll(/href="(diagrams\/[^"]+\.html)"/g)].map((match) => match[1])

if (links.length !== 17 || new Set(links).size !== links.length) {
  throw new Error('Expected 17 unique diagram links, found ' + links.length)
}

const payloads = await Promise.all(links.map(async (link) => {
  const html = await readFile(resolve(architectureDirectory, link))
  return '<script type="application/octet-stream" data-diagram="' + link + '">' + gzipSync(html).toString('base64') + '</script>'
}))

const opener = '<script>\n' +
  '  const diagramPayloads = new Map([...document.querySelectorAll("script[data-diagram]")].map((element) => [element.dataset.diagram, element.textContent.trim()]))\n' +
  '  document.addEventListener("click", async (event) => {\n' +
  '    const card = event.target.closest("a.card")\n' +
  '    if (!card || !diagramPayloads.has(card.getAttribute("href"))) return\n' +
  '    event.preventDefault()\n' +
  '    const page = window.open("", "_blank")\n' +
  '    if (!page) {\n' +
  '      window.alert("浏览器拦截了新窗口。请允许弹窗后重试，或先解压 ZIP 再打开 index.html。")\n' +
  '      return\n' +
  '    }\n' +
  '    try {\n' +
  '      page.document.title = "正在打开架构图…"\n' +
  '      const encoded = diagramPayloads.get(card.getAttribute("href"))\n' +
  '      const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0))\n' +
  '      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))\n' +
  '      const html = await new Response(stream).text()\n' +
  '      page.document.open()\n' +
  '      page.document.write(html)\n' +
  '      page.document.close()\n' +
  '    } catch (error) {\n' +
  '      page.document.body.textContent = "打开架构图失败。请先解压 ZIP，再从 index.html 打开。"\n' +
  '      console.error(error)\n' +
  '    }\n' +
  '  })\n' +
  '</script>'

const standalone = source.replace('</body>', payloads.join('\n') + '\n' + opener + '\n</body>')
await writeFile(resolve(outputPath), standalone)
