import { computed, ref } from "vue";

import { listModels } from "../lib/api";
import { reportError } from "../lib/toast";
import type { LlmModel } from "../types";

export function useModels() {
  const models = ref<LlmModel[]>([]);

  const active = computed(() => models.value.filter((model) => model.is_active));
  const defaultModel = computed(
    () => active.value.find((model) => model.is_default) ?? active.value[0] ?? null,
  );

  async function refresh(): Promise<void> {
    try {
      models.value = (await listModels()).items;
    } catch (cause) {
      reportError(cause);
    }
  }

  /** 退出登录/换账号：模型列表和密钥都是按账号隔离的，清掉。 */
  function reset(): void {
    models.value = [];
  }

  return { models, active, defaultModel, refresh, reset };
}
