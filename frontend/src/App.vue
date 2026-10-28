<script setup lang="ts">
import { Bird, LoaderCircle, RefreshCcw, Settings2 } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import AppSidebar from "./components/AppSidebar.vue";
import AuthGate from "./components/AuthGate.vue";
import ChatView from "./components/ChatView.vue";
import DraftHome from "./components/DraftHome.vue";
import ConfirmDialog from "./components/ConfirmDialog.vue";
import SettingsDialog from "./components/SettingsDialog.vue";
import SurfacePanel from "./components/SurfacePanel.vue";
import ToastStack from "./components/ToastStack.vue";
import { useGroups } from "./composables/useGroups";
import { useModels } from "./composables/useModels";
import { useSessions } from "./composables/useSessions";
import { useSurfaces } from "./composables/useSurfaces";
import { currentUser, hasSession, logout, probeSession } from "./lib/auth";
import type {
  OutgoingAttachment,
  OutgoingResource,
  Session,
  SessionGroup,
  SettingsSection,
} from "./types";

const {
  sessions,
  refresh: refreshSessions,
  create: createSession,
  rename,
  remove: removeSession,
  reset: resetSessions,
} = useSessions();
const {
  models,
  active: activeModels,
  defaultModel,
  refresh: refreshModels,
  reset: resetModels,
} = useModels();
const {
  groups,
  collapsed,
  refresh: refreshGroups,
  toggle: toggleGroup,
  create: createGroup,
  rename: renameGroup,
  remove: removeGroup,
  moveTo,
  reset: resetGroups,
} = useGroups();

const activeSessionId = ref<string | null>(null);
const surfaces = useSurfaces();
const selectedModelId = ref<number | null>(null);
const sidebarOpen = ref(!window.matchMedia("(max-width: 767px)").matches);
const settingsOpen = ref(false);
const settingsSection = ref<SettingsSection>("models");
const booting = ref(true);
const bootError = ref<string | null>(null);
const removeTarget = ref<Session | null>(null);
const removeGroupTarget = ref<SessionGroup | null>(null);
/** 草稿态：没有会话，第一条消息发出去时才建。 */
const drafting = ref(false);
const pendingGroupId = ref<number | null>(null);
const initialMessage = ref<{
  input: string;
  attachments: OutgoingAttachment[];
  resources?: OutgoingResource[];
} | null>(null);
let creatingDraft = false;

const activeSession = computed(
  () => sessions.value.find((session) => session.id === activeSessionId.value) ?? null,
);

function isMobile(): boolean {
  return window.matchMedia("(max-width: 767px)").matches;
}

function selectSession(sessionId: string) {
  drafting.value = false;
  pendingGroupId.value = null;
  activeSessionId.value = sessionId;
  const hit = sessions.value.find((session) => session.id === sessionId);
  if (hit?.model_id != null) selectedModelId.value = hit.model_id;
  if (isMobile()) sidebarOpen.value = false;
}

function openSettings(section: SettingsSection = "models") {
  settingsSection.value = section;
  settingsOpen.value = true;
}

function startNew(groupId?: number) {
  if (activeModels.value.length === 0) {
    openSettings();
    return;
  }
  pendingGroupId.value = groupId ?? null;
  activeSessionId.value = null;
  drafting.value = true;
  if (isMobile()) sidebarOpen.value = false;
}

/** 草稿页发送：先建会话，再把这条消息交给它发出去。 */
async function onDraftSend(payload: {
  input: string;
  attachments: OutgoingAttachment[];
  resources?: OutgoingResource[];
}) {
  if (creatingDraft) return;
  creatingDraft = true;
  try {
    const created = await createSession(
      selectedModelId.value ?? defaultModel.value?.id ?? null,
      pendingGroupId.value,
    );
    if (!created) return;
    initialMessage.value = payload;
    pendingGroupId.value = null;
    selectSession(created.id);
  } finally {
    creatingDraft = false;
  }
}

async function bootstrap() {
  booting.value = true;
  bootError.value = null;
  try {
    await Promise.all([refreshModels(), refreshSessions(), refreshGroups()]);
    if (sessions.value.length > 0) selectSession(sessions.value[0].id);
    else startNew();
  } catch (cause) {
    bootError.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    booting.value = false;
  }
}

watch(defaultModel, (model) => {
  if (model && selectedModelId.value == null) selectedModelId.value = model.id;
});

watch(
  () => sessions.value.length,
  () => {
    // 停在草稿页时别抢回去：用户可能就是想在草稿里发第一条
    if (!activeSessionId.value && !drafting.value && sessions.value.length > 0) {
      selectSession(sessions.value[0].id);
    }
  },
);

// 预览面板属于当前会话，切会话就整栈收掉
watch(activeSessionId, () => surfaces.clear());

async function onRename(sessionId: string, title: string) {
  await rename(sessionId, title);
}

function askRemove(session: Session) {
  removeTarget.value = session;
}

async function confirmRemove() {
  const target = removeTarget.value;
  removeTarget.value = null;
  if (!target) return;
  await removeSession(target.id);
  if (activeSessionId.value !== target.id) return;
  const next = sessions.value[0];
  if (next) selectSession(next.id);
  else startNew();
}

/** 会话在别处被删掉了：退掉这个空壳，重新挑一条（列表也要跟着换新的）。 */
async function onSessionGone() {
  activeSessionId.value = null;
  await Promise.all([refreshSessions(), refreshGroups()]);
  const next = sessions.value[0];
  if (next) selectSession(next.id);
  else startNew();
}

async function onSettingsChanged() {
  await refreshModels();
  await refreshSessions();
  await refreshGroups();
  const available = activeModels.value;
  if (
    selectedModelId.value == null ||
    !available.some((model) => model.id === selectedModelId.value)
  ) {
    selectedModelId.value = defaultModel.value?.id ?? available[0]?.id ?? null;
  }
}

function onModelChange(modelId: number) {
  selectedModelId.value = modelId;
  const current = activeSession.value;
  if (current) current.model_id = modelId;
}

async function onRunEnd() {
  await refreshSessions();
  await refreshGroups();
}

async function onMove(session: Session, groupId: number | null) {
  await moveTo(session, groupId);
  await refreshGroups();
}

async function confirmRemoveGroup() {
  const target = removeGroupTarget.value;
  removeGroupTarget.value = null;
  if (target) await removeGroup(target.id);
}

onMounted(() => {
  // 有 token 就先用 /auth/me 确认一次，身份确认后自动 bootstrap
  if (hasSession()) void probeSession().then(() => void bootstrapWhenAuthed());
});

/** 登录身份出现的瞬间做一次全量引导；登出后再登录同样复用这里。 */
let bootstrappedForUser: string | null = null;
async function bootstrapWhenAuthed() {
  const user = currentUser.value;
  if (!user || bootstrappedForUser === user.id) return;
  bootstrappedForUser = user.id;
  await bootstrap();
}

/** 退出登录/会话失效：账号相关的东西全部清掉，换账号时不带过去。 */
function resetWorkspace(): void {
  resetSessions();
  resetModels();
  resetGroups();
  activeSessionId.value = null;
  selectedModelId.value = null;
  drafting.value = false;
  pendingGroupId.value = null;
  initialMessage.value = null;
  settingsOpen.value = false;
  surfaces.clear();
}

function onLogout(): void {
  logout();
}

watch(currentUser, (user) => {
  if (!user) {
    resetWorkspace();
    bootstrappedForUser = null;
    return;
  }
  void bootstrapWhenAuthed();
});

</script>

<template>
  <div v-if="!currentUser" class="flex h-full min-h-0 flex-col">
    <AuthGate class="flex-1" />
  </div>
  <div v-else class="flex h-full min-h-0 bg-canvas">
    <div
      v-if="sidebarOpen"
      class="h-full shrink-0 max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-30 max-md:shadow-float"
    >
      <AppSidebar
        :sessions="sessions"
        :groups="groups"
        :collapsed="[...collapsed]"
        :active-id="activeSessionId"
        :user="currentUser"
        @select="selectSession"
        @new="startNew"
        @collapse="sidebarOpen = false"
        @rename="onRename"
        @remove="askRemove"
        @move="onMove"
        @create-group="(name) => void createGroup(name)"
        @rename-group="(id, name) => void renameGroup(id, name)"
        @remove-group="(group) => (removeGroupTarget = group)"
        @toggle-group="toggleGroup"
        @settings="openSettings('models')"
        @profile="openSettings('profile')"
        @logout="onLogout"
      />
    </div>
    <button
      v-if="sidebarOpen"
      class="fixed inset-0 z-20 bg-black/20 md:hidden"
      aria-label="收起侧栏"
      @click="sidebarOpen = false"
    />

    <ChatView
      v-if="activeSessionId"
      :key="activeSessionId"
      :session-id="activeSessionId"
      :sidebar-open="sidebarOpen"
      :models="models"
      :model-id="selectedModelId"
      :groups="groups"
      :sessions="sessions"
      @toggle-sidebar="sidebarOpen = true"
      @open-session="selectSession"
      @new-in-group="(groupId: number) => void startNew(groupId)"
      @create-group="(name: string) => void createGroup(name)"
      :initial-message="initialMessage"
      @initial-consumed="initialMessage = null"
      @run-end="onRunEnd"
      @session-gone="onSessionGone"
      @open-settings="openSettings()"
      @model-change="onModelChange"
    />

    <DraftHome
      v-else-if="!booting && !bootError"
      :models="models"
      :model-id="selectedModelId"
      :sidebar-open="sidebarOpen"
      @send="onDraftSend"
      @model-change="onModelChange"
      @toggle-sidebar="sidebarOpen = true"
      @open-settings="openSettings()"
    />

    <div v-else class="flex flex-1 flex-col items-center justify-center gap-4 px-6">
      <div class="grid size-11 place-items-center rounded-float bg-ink text-canvas">
        <Bird v-if="!booting" :size="22" :stroke-width="1.7" />
        <LoaderCircle v-else :size="20" class="animate-spin" />
      </div>
      <p class="text-ui text-muted">
        {{ booting ? "正在准备会话…" : bootError ?? "还没有会话" }}
      </p>
      <div v-if="!booting" class="flex items-center gap-2">
        <button class="btn btn-ghost border border-hair" @click="bootstrap">
          <RefreshCcw :size="13" />重试
        </button>
        <button class="btn btn-primary" @click="openSettings()">
          <Settings2 :size="13" />模型设置
        </button>
      </div>
    </div>

    <SurfacePanel />

    <SettingsDialog
      v-model:open="settingsOpen"
      v-model:section="settingsSection"
      :models="models"
      :user="currentUser"
      @changed="onSettingsChanged"
      @logout="onLogout"
    />
    <ConfirmDialog
      :open="removeTarget !== null"
      title="删除这个会话？"
      :message="`「${removeTarget?.title?.trim() || '未命名会话'}」及其全部消息都会被删除。`"
      confirm-label="删除会话"
      @confirm="confirmRemove"
      @cancel="removeTarget = null"
    />
    <ConfirmDialog
      :open="removeGroupTarget !== null"
      title="删除这个分组？"
      :message="`「${removeGroupTarget?.name ?? ''}」会被删掉，组里的 ${removeGroupTarget?.session_count ?? 0} 条会话回到未分组。`"
      confirm-label="删除分组"
      @confirm="confirmRemoveGroup"
      @cancel="removeGroupTarget = null"
    />
  </div>

  <ToastStack />
</template>
