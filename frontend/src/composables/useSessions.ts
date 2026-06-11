import { computed, ref, watch } from 'vue'

import type { FeedItem } from './useFeed'

// 一个会话 = 一条独立的消息流 + 一个唯一 session_id。
// 后端按 session_id 维护 context 快照，所以这里的 sessionId 直接决定服务端多轮连续性。
export interface ChatSession {
  id: string
  title: string
  sessionId: string
  createdAt: number
  feed: FeedItem[]
}

const SESSIONS_KEY = 'cyrene.sessions'
const ACTIVE_KEY = 'cyrene.activeSession'
const MAX_TITLE_LENGTH = 24

function randomId() {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && 'randomUUID' in cryptoObj) {
    return cryptoObj.randomUUID().replace(/-/g, '').slice(0, 12)
  }
  return Math.random().toString(36).slice(2, 14)
}

function createBlankSession(): ChatSession {
  const id = randomId()
  return {
    id,
    title: '新对话',
    // 每个会话独立的服务端会话标识，替换原先硬编码的 'http'。
    sessionId: `web-${id}`,
    createdAt: Date.now(),
    feed: [],
  }
}

function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    // 只保留结构完整的会话，避免旧数据/脏数据导致整页崩溃。
    return parsed.filter(
      (item): item is ChatSession =>
        !!item &&
        typeof item.id === 'string' &&
        typeof item.sessionId === 'string' &&
        Array.isArray(item.feed)
    )
  } catch {
    return []
  }
}

const sessions = ref<ChatSession[]>(loadSessions())
const activeSessionId = ref<string>('')

// 初始化：恢复上次激活的会话；没有任何会话则建一个空会话。
function initActiveSession() {
  const stored = localStorage.getItem(ACTIVE_KEY)
  if (stored && sessions.value.some((session) => session.id === stored)) {
    activeSessionId.value = stored
    return
  }
  if (sessions.value.length === 0) {
    const blank = createBlankSession()
    sessions.value.push(blank)
    activeSessionId.value = blank.id
    return
  }
  activeSessionId.value = sessions.value[0].id
}

initActiveSession()

const activeSession = computed(
  () =>
    sessions.value.find((session) => session.id === activeSessionId.value) ??
    sessions.value[0]
)

// 持久化：会话内容或激活项变化都写回 localStorage。
watch(
  sessions,
  (value) => {
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(value))
    } catch {
      // 存储失败（如隐私模式）静默降级，不影响使用。
    }
  },
  { deep: true }
)

watch(activeSessionId, (value) => {
  try {
    localStorage.setItem(ACTIVE_KEY, value)
  } catch {
    // 同上：静默降级。
  }
})

// 标题取首条用户消息前若干字，便于在列表里区分会话。
function deriveTitle(session: ChatSession) {
  const firstUser = session.feed.find((item) => item.kind === 'user' && item.content)
  if (!firstUser?.content) return '新对话'
  const text = firstUser.content.trim().replace(/\s+/g, ' ')
  return text.length > MAX_TITLE_LENGTH ? `${text.slice(0, MAX_TITLE_LENGTH)}…` : text
}

function syncTitle(session: ChatSession) {
  session.title = deriveTitle(session)
}

function createSession() {
  const blank = createBlankSession()
  sessions.value.unshift(blank)
  activeSessionId.value = blank.id
  return blank
}

function switchSession(id: string) {
  if (sessions.value.some((session) => session.id === id)) {
    activeSessionId.value = id
  }
}

function deleteSession(id: string) {
  const next = sessions.value.filter((session) => session.id !== id)
  sessions.value = next.length > 0 ? next : [createBlankSession()]
  if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
    activeSessionId.value = sessions.value[0].id
  }
}

export function useSessions() {
  return {
    sessions,
    activeSessionId,
    activeSession,
    createSession,
    switchSession,
    deleteSession,
    syncTitle,
  }
}
