const { build } = await import(process.env.ESBUILD_ENTRY ?? 'esbuild')
import fs from 'node:fs'
const FE = process.argv[2], OUT = process.argv[3], HERE = new URL('.', import.meta.url).pathname
fs.mkdirSync(OUT, { recursive: true })
await build({
  entryPoints: [FE + '/src/main.jsx'], bundle: true, outfile: OUT + '/bundle.js', format: 'esm', jsx: 'automatic',
  nodePaths: process.env.NODE_MODULES_DIR ? [process.env.NODE_MODULES_DIR] : [], loader: { '.js': 'jsx', '.css': 'empty' },
  define: { 'import.meta.env': '{"VITE_API_BASE_URL":""}', 'process.env.NODE_ENV': '"production"' },
  alias: { 'react-markdown': HERE + 'stubs/react-markdown.jsx', 'remark-gfm': HERE + 'stubs/remark-gfm.js',
           'rehype-sanitize': HERE + 'stubs/rehype-sanitize.js', 'react-virtuoso': HERE + 'stubs/react-virtuoso.jsx',
           'react-syntax-highlighter/dist/esm/styles/prism': HERE + 'stubs/prism-style.js',
           'react-syntax-highlighter': HERE + 'stubs/react-syntax-highlighter.js' },
  logLevel: 'warning',
})
fs.writeFileSync(OUT + '/index.html', `<!doctype html><html lang="en" class="dark"><head><meta charset="utf-8"><title>Clinical Knowledge Assistant (smoke build)</title>
<style>body{font-family:sans-serif;margin:0;background:#07070f;color:#e8e8f4}#root{height:100vh}.hidden{display:none}@media(min-width:1280px){.xl\\:flex{display:flex}}@media(min-width:768px){.md\\:flex{display:flex}}.flex{display:flex}.flex-col{flex-direction:column}.h-full{height:100%}.flex-1{flex:1}.sr-only{position:absolute;left:-9999px}</style></head>
<body><div id="app-loader"></div><div id="root"></div><script type="module" src="/bundle.js"></script></body></html>`)
console.log('built', fs.statSync(OUT + '/bundle.js').size, 'bytes')
