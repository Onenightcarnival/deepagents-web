import { createApp } from "vue";

import App from "./App.vue";

// 挂载点：public/index.html 中的 #settings-root；开发页 frontend/index.html 同名
let el = document.getElementById("settings-root");
if (!el) {
  el = document.createElement("div");
  el.id = "settings-root";
  document.body.appendChild(el);
}
createApp(App).mount(el);
