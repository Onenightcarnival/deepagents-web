<script setup>
import { darkTheme, NConfigProvider, NDialogProvider, NMessageProvider, zhCN } from "naive-ui";
import { onBeforeUnmount, onMounted, ref } from "vue";

import { api } from "./api.js";
import SettingsOverlay from "./SettingsOverlay.vue";
import { store } from "./store.js";

const open = ref(false);

async function handleOpen() {
  store.config = await api("/settings/").catch(() => null);
  open.value = true;
}

onMounted(() => document.addEventListener("settings:open", handleOpen));
onBeforeUnmount(() => document.removeEventListener("settings:open", handleOpen));

// GitHub Dark 配色，与宿主页面 css 变量保持一致
const themeOverrides = {
  common: {
    primaryColor: "#58a6ff",
    primaryColorHover: "#388bfd",
    primaryColorPressed: "#1f6feb",
    bodyColor: "#0d1117",
    cardColor: "#161b22",
    modalColor: "#161b22",
    popoverColor: "#21262d",
    borderColor: "#30363d",
    textColorBase: "#e6edf3",
    textColor1: "#e6edf3",
    textColor2: "#e6edf3",
    textColor3: "#8b949e",
    errorColor: "#f85149",
    successColor: "#3fb950",
    warningColor: "#d29922",
  },
};
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="themeOverrides" :locale="zhCN">
    <NMessageProvider>
      <NDialogProvider>
        <SettingsOverlay v-if="open" @close="open = false" />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
