import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/main.css'

const app = createApp(App)

// Pinia MUST be registered before Router
// Router guards use Pinia stores — registering Router first causes
// "no active Pinia" errors during navigation guard execution
app.use(createPinia())
app.use(router)

app.mount('#app')
