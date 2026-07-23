import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'

// Keep formula rendering self-contained for offline evaluator machines.
window.katex = katex

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
