import { computed, reactive, ref, type Component } from 'vue'

import { Bot, Image as ImageIcon, MessageSquareText } from '@lucide/vue'

import {
  ApiError,
  chat,
  chatStream,
  generateImage,
  runAgent,
  type AgentRunResponse,
  type ChatResponse,
  type GeneratedImage,
} from '../api'
import { contentToText, nullableInteger, nullableNumber } from '../utils/format'
import { useNotify } from './useNotify'
import { useProviders } from './useProviders'
import { useSessions } from './useSessions'

export type ComposerMode = 'chat' | 'agent' | 'image'

export const composerModes: Array<{ key: ComposerMode; label: string; icon: Component }> = [
  { key: 'chat', label: '对话', icon: MessageSquareText },
  { key: 'agent', label: 'Agent', icon: Bot },
  { key: 'image', label: '图像', icon: ImageIcon },
]

export interface FeedItem {
  id: number
  kind: 'user' | 'assistant' | 'agent' | 'images' | 'error'
  // 通用文本内容（user/assistant 用；agent 存最终回复）
  content?: string
  model?: string
  time?: string
  toolCalls?: any[]
  toolResults?: any[]
  // agent 模式专属
  agentSteps?: AgentRunResponse['steps']
  agentStopReason?: string
  // image 模式专属
  images?: GeneratedImage[]
  prompt?: string
  // error 模式专属：在消息流里保留失败详情，方便排查供应商/模型连通性
  errorMode?: ComposerMode
  errorStatus?: number
  errorDetail?: string
  // 失败请求的原始载荷，供「重试」复用
  retry?: PendingRequest
  // 进行中标记（用于流式占位/loading）
  pending?: boolean
}

const composerMode = ref<ComposerMode>('chat')
const submitting = ref(false)

const { activeSession, sessions, syncTitle } = useSessions()

// feed 始终指向当前激活会话的消息流：读写都落到该会话，切换会话即切换 feed。
const feed = computed<FeedItem[]>({
  get: () => activeSession.value?.feed ?? [],
  set: (value) => {
    if (activeSession.value) activeSession.value.feed = value
  },
})
const chatResult = ref<ChatResponse | null>(null)
const previewImage = ref<GeneratedImage | null>(null)

const chatForm = reactive({
  system: '',
  prompt: '',
  temperature: '',
  maxTokens: '',
  maxToolRounds: 1,
  allowTools: true,
  stream: true,
})

const agentForm = reactive({
  goal: '',
  message: '',
  maxSteps: 4,
  planningEnabled: true,
  replanningEnabled: true,
  memoryEnabled: false,
  maxToolCallsPerStep: '',
  maxTotalToolCalls: '',
})

const imageForm = reactive({
  prompt: '',
  count: 1,
  size: '1024x1024',
  quality: 'standard',
  responseFormat: 'b64_json' as 'b64_json' | 'url',
})

// feed 条目自增 ID，避免不同模式间 Date.now() 撞号。
// 从持久化会话里已有的最大 id 起步，防止刷新后新条目与旧条目撞号。
let feedSeq = sessions.value.reduce(
  (max, session) =>
    session.feed.reduce((inner, item) => Math.max(inner, item.id ?? 0), max),
  0
)
function nextFeedId() {
  feedSeq += 1
  return feedSeq
}

const { showToast, showApiError } = useNotify()
const { selectedProviderId, selectedModel } = useProviders()

function clearFeed() {
  feed.value = []
  chatResult.value = null
}

// 失败请求的可重发载荷，挂在错误条目上，供「重试」按钮复用。
type PendingRequest =
  | { mode: 'chat'; body: Record<string, unknown> }
  | { mode: 'agent'; body: Record<string, unknown> }
  | { mode: 'image'; body: Record<string, unknown>; prompt: string }

// 把任意错误拆成 状态码 + 详情，保留到消息流里，而不是只弹一个会消失的 toast。
function describeError(error: unknown): { status?: number; detail: string } {
  if (error instanceof ApiError) {
    return { status: error.status, detail: error.message || '请求失败' }
  }
  if (error instanceof Error) {
    return { detail: error.message || '请求失败' }
  }
  return { detail: '请求失败' }
}

// 失败时：消息流里追加一条可见的错误条目（含重试载荷），同时保留 toast 的鉴权跳转。
function pushError(request: PendingRequest, error: unknown) {
  const { status, detail } = describeError(error)
  feed.value.push({
    id: nextFeedId(),
    kind: 'error',
    errorMode: request.mode,
    errorStatus: status,
    errorDetail: detail,
    prompt: request.mode === 'image' ? request.prompt : undefined,
    retry: request,
    time: new Date().toLocaleTimeString(),
  })
  // 鉴权失败仍走原有逻辑：弹登录框。
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    showApiError(error, modeFailureLabel(request.mode))
  }
}

function modeFailureLabel(mode: ComposerMode) {
  if (mode === 'chat') return '对话请求失败'
  if (mode === 'agent') return 'Agent 运行失败'
  return '图像生成失败'
}

// 收到成功结果后，把对应模式的回复追加进消息流。
function pushChatReply(result: ChatResponse) {
  chatResult.value = result
  const replyText = contentToText(result?.response?.message?.content) || ''
  feed.value.push({
    id: nextFeedId(),
    kind: 'assistant',
    content: replyText,
    model: result?.response?.model,
    time: new Date().toLocaleTimeString(),
    toolCalls: result?.response?.tool_calls || [],
    toolResults: result?.tool_results || [],
  })
  showToast('success', '已收到模型回复')
}

function pushAgentReply(result: AgentRunResponse) {
  feed.value.push({
    id: nextFeedId(),
    kind: 'agent',
    content: contentToText(result.response?.message?.content) || '',
    model: result.response?.model,
    time: new Date().toLocaleTimeString(),
    agentSteps: result.steps ?? [],
    agentStopReason: result.stop_reason,
  })
  showToast('success', 'Agent 运行完成')
}

function pushImageReply(images: GeneratedImage[], prompt: string) {
  feed.value.push({
    id: nextFeedId(),
    kind: 'images',
    images,
    prompt,
    time: new Date().toLocaleTimeString(),
  })
  showToast('success', '图像生成完成')
}

// 统一执行入口：负责调用 API、分派成功/失败处理，并维护 submitting 标记。
async function execute(request: PendingRequest) {
  submitting.value = true
  try {
    if (request.mode === 'chat') {
      pushChatReply(await chat(request.body))
    } else if (request.mode === 'agent') {
      pushAgentReply(await runAgent(request.body))
    } else {
      const res = await generateImage(request.body)
      pushImageReply(res.response.images || [], request.prompt)
    }
  } catch (error) {
    pushError(request, error)
  } finally {
    submitting.value = false
  }
}

// 流式执行：先插入一个 pending 的 assistant 占位项，按 SSE 事件实时填充。
// 失败时移除占位项并落入可重试的错误条目（复用非流式的 pushError）。
async function executeStream(body: Record<string, unknown>) {
  submitting.value = true
  const placeholder: FeedItem = {
    id: nextFeedId(),
    kind: 'assistant',
    content: '',
    time: new Date().toLocaleTimeString(),
    toolCalls: [],
    toolResults: [],
    pending: true,
  }
  feed.value.push(placeholder)
  // 拿到 feed 里的真实对象引用，后续直接原地修改（深层响应式会刷新视图）。
  const item = feed.value.find((entry) => entry.id === placeholder.id) ?? placeholder
  let received = false

  try {
    await chatStream(body, {
      onDelta: (text) => {
        received = true
        item.content = (item.content || '') + text
      },
      onToolCall: (calls) => {
        item.toolCalls = [...(item.toolCalls || []), ...calls]
      },
      onToolResult: (results) => {
        item.toolResults = [...(item.toolResults || []), ...results]
      },
      onDone: (event) => {
        item.pending = false
        if (event.finish_reason) {
          chatResult.value = {
            response: {
              provider_id: '',
              model: (body.model as string) ?? '',
              finish_reason: event.finish_reason,
            },
          } as ChatResponse
        }
        item.model = (body.model as string) ?? item.model
      },
      onError: (detail) => {
        throw new ApiError(0, detail, { detail })
      },
    })
    item.pending = false
    if (!received && !(item.toolResults && item.toolResults.length)) {
      item.content = item.content || '(无内容返回)'
    }
    showToast('success', '已收到模型回复')
  } catch (error) {
    // 移除占位项，把失败转成统一的可重试错误卡片。
    feed.value = feed.value.filter((entry) => entry.id !== placeholder.id)
    pushError({ mode: 'chat', body }, error)
  } finally {
    submitting.value = false
  }
}

// 重试某条错误：移除该错误条目，复用其载荷重新发送。
// 流式聊天失败保存的载荷带 stream:true，重试时仍走流式路径。
function retryItem(item: FeedItem) {
  if (submitting.value || item.kind !== 'error' || !item.retry) return
  const request = item.retry
  feed.value = feed.value.filter((entry) => entry.id !== item.id)
  if (request.mode === 'chat' && request.body.stream === true) {
    void executeStream(request.body)
    return
  }
  void execute(request)
}

// 关闭某条错误条目（不重试）。
function dismissItem(item: FeedItem) {
  feed.value = feed.value.filter((entry) => entry.id !== item.id)
}

// 当前激活会话的服务端会话标识。
function currentSessionId() {
  return activeSession.value?.sessionId ?? 'web'
}

// 追加一条用户消息，并据此刷新会话标题。
function pushUser(content: string) {
  feed.value.push({ id: nextFeedId(), kind: 'user', content })
  if (activeSession.value) syncTitle(activeSession.value)
}

function submitChat() {
  if (!selectedProviderId.value || !selectedModel.value || !chatForm.prompt.trim()) {
    showToast('error', '请选择供应商、模型，并填写提示词')
    return
  }
  const userPrompt = chatForm.prompt.trim()
  pushUser(userPrompt)
  chatForm.prompt = ''

  // 多轮历史由后端按 session_id 维护，前端只发当前输入 + 可选 system，避免上下文翻倍。
  const messages: Array<{ role: string; content: string }> = []
  if (chatForm.system.trim()) {
    messages.push({ role: 'system', content: chatForm.system.trim() })
  }
  messages.push({ role: 'user', content: userPrompt })

  const body: Record<string, unknown> = {
    provider_id: selectedProviderId.value,
    model: selectedModel.value,
    messages,
    temperature: nullableNumber(chatForm.temperature),
    max_tokens: nullableInteger(chatForm.maxTokens),
    max_tool_rounds: chatForm.allowTools ? chatForm.maxToolRounds : 0,
    stream: chatForm.stream,
    metadata: {
      session_id: currentSessionId(),
      source: 'frontend-console',
    },
  }

  if (chatForm.stream) {
    return executeStream(body)
  }
  return execute({ mode: 'chat', body })
}

function submitAgent() {
  if (!selectedProviderId.value || !selectedModel.value || !agentForm.goal.trim()) {
    showToast('error', '请选择供应商、模型，并填写目标')
    return
  }
  pushUser(agentForm.goal.trim())

  return execute({
    mode: 'agent',
    body: {
      provider_id: selectedProviderId.value,
      model: selectedModel.value,
      goal: agentForm.goal.trim(),
      messages: agentForm.message.trim()
        ? [{ role: 'user', content: agentForm.message.trim() }]
        : [],
      max_steps: agentForm.maxSteps,
      planning: {
        enabled: agentForm.planningEnabled,
        replanning_enabled: agentForm.replanningEnabled,
      },
      memory_retrieval: agentForm.memoryEnabled
        ? {
            enabled: true,
            max_results: 4,
          }
        : null,
      max_tool_calls_per_step: nullableInteger(agentForm.maxToolCallsPerStep),
      max_total_tool_calls: nullableInteger(agentForm.maxTotalToolCalls),
      metadata: {
        session_id: currentSessionId(),
        source: 'frontend-console',
      },
    },
  })
}

function submitImage() {
  if (!selectedProviderId.value || !selectedModel.value || !imageForm.prompt.trim()) {
    showToast('error', '请选择供应商、模型，并填写提示词')
    return
  }
  const prompt = imageForm.prompt.trim()
  pushUser(prompt)

  return execute({
    mode: 'image',
    prompt,
    body: {
      provider_id: selectedProviderId.value,
      model: selectedModel.value,
      prompt,
      count: Number(imageForm.count),
      size: imageForm.size,
      quality: imageForm.quality,
      response_format: imageForm.responseFormat,
      metadata: {
        session_id: `${currentSessionId()}-image`,
        source: 'frontend-console',
      },
    },
  })
}

// composer 统一分派：按当前模式调用对应提交逻辑。
function submitComposer() {
  if (submitting.value) return
  if (composerMode.value === 'chat') return submitChat()
  if (composerMode.value === 'agent') return submitAgent()
  return submitImage()
}

function addPreset(presetText: string) {
  if (imageForm.prompt) {
    imageForm.prompt += ', ' + presetText
  } else {
    imageForm.prompt = presetText
  }
}

const composerFooter = computed(
  () =>
    chatResult.value?.stop_reason ||
    chatResult.value?.response?.finish_reason ||
    'Ctrl+Enter 发送'
)

const composerModeMeta = computed(
  () => composerModes.find((mode) => mode.key === composerMode.value) ?? composerModes[0]
)

export function useFeed() {
  return {
    composerMode,
    composerModeMeta,
    submitting,
    feed,
    chatResult,
    previewImage,
    chatForm,
    agentForm,
    imageForm,
    composerFooter,
    clearFeed,
    submitComposer,
    retryItem,
    dismissItem,
    addPreset,
  }
}
