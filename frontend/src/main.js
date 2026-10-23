import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import mermaid from 'mermaid'
import Prism from 'prismjs'
import 'prismjs/themes/prism-tomorrow.css'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-java'
import 'prismjs/components/prism-c'
import 'prismjs/components/prism-cpp'
import 'prismjs/components/prism-csharp'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-sql'
import 'prismjs/components/prism-markdown'

// Keep formula, diagram, and code rendering self-contained for evaluator machines.
window.katex = katex
window.mermaid = mermaid
window.Prism = Prism

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
