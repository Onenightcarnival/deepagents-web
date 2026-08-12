import { reactive } from "vue";

// 设置应用内的共享状态（跨面板）
export const store = reactive({
  config: null,          // GET /settings 的结果
  providersDirty: false, // 模型服务面板有未保存修改（关闭设置时需要确认）
});
