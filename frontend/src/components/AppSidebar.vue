<script setup lang="ts">
import { Cpu, KeyRound, MessageSquareText, RefreshCw, Square, Trash2 } from '@lucide/vue'

import { useAuth } from '../composables/useAuth'
import { useConsole, views } from '../composables/useConsole'
import { useHealth } from '../composables/useHealth'
import { usePlugins } from '../composables/usePlugins'
import { useSessions } from '../composables/useSessions'
import { statusLabel } from '../utils/format'

const { activeView, loading, refreshAll } = useConsole()
const { healthStatus, readyStatus } = useHealth()
const { plugins, enabledPlugins, failedPlugins } = usePlugins()
const { authOpen, submitLogout } = useAuth()
const { sessions, activeSessionId, createSession, switchSession, deleteSession } = useSessions()

function startNewChat() {
  activeView.value = 'workspace'
  createSession()
}

function openSession(id: string) {
  activeView.value = 'workspace'
  switchSession(id)
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">
        <Cpu :size="20" />
      </div>
      <div>
        <strong>CyreneBot</strong>
        <span>控制台</span>
      </div>
    </div>

    <button class="new-chat-button" type="button" @click="startNewChat">
      <MessageSquareText :size="18" />
      新对话
    </button>

    <nav class="nav-list" aria-label="主导航">
      <button
        v-for="view in views"
        :key="view.key"
        class="nav-item"
        :class="{ active: activeView === view.key }"
        type="button"
        @click="activeView = view.key"
      >
        <component :is="view.icon" :size="18" />
        <span>{{ view.label }}</span>
      </button>
    </nav>

    <div class="session-list" aria-label="会话列表">
      <div class="block-title">会话</div>
      <button
        v-for="session in sessions"
        :key="session.id"
        class="session-item"
        :class="{ active: activeView === 'workspace' && activeSessionId === session.id }"
        type="button"
        @click="openSession(session.id)"
      >
        <span class="session-title">{{ session.title }}</span>
        <span
          class="session-delete"
          title="删除会话"
          @click.stop="deleteSession(session.id)"
        >
          <Trash2 :size="14" />
        </span>
      </button>
    </div>

    <div class="sidebar-block">
      <div class="block-title">运行状态</div>
      <div class="signal-row">
        <span class="status-dot" :class="healthStatus" />
        <span>API {{ statusLabel(healthStatus) }}</span>
      </div>
      <div class="signal-row">
        <span class="status-dot" :class="readyStatus" />
        <span>运行时 {{ statusLabel(readyStatus) }}</span>
      </div>
      <div class="signal-row">
        <span class="status-dot" :class="failedPlugins ? 'error' : 'ready'" />
        <span>插件 {{ enabledPlugins }}/{{ plugins.length }}</span>
      </div>
      <div class="signal-row" v-if="failedPlugins">
        <span class="status-dot error" />
        <span>异常 {{ failedPlugins }}</span>
      </div>
    </div>

    <div class="sidebar-actions">
      <button class="icon-button" type="button" title="刷新" @click="refreshAll">
        <RefreshCw :size="18" :class="{ spin: loading }" />
      </button>
      <button class="icon-button" type="button" title="登录" @click="authOpen = true">
        <KeyRound :size="18" />
      </button>
      <button class="icon-button" type="button" title="退出登录" @click="submitLogout">
        <Square :size="18" />
      </button>
    </div>
  </aside>
</template>
