export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(status: number, message: string, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

export interface ProviderInfo {
  provider_type: string
  name: string
  description: string
  models?: string[] | null
  capabilities?: string[] | null
  features?: string[] | null
}

export interface ProviderModel {
  model_id: string
  name?: string | null
  metadata?: Record<string, string>
}

export interface ProviderConfigSummary {
  provider_id: string
  provider_type: string
  has_api_key: boolean
  base_url?: string | null
  timeout?: string | number | null
  enabled: boolean
  models?: ProviderModel[]
  metadata?: Record<string, string>
}

export interface ProviderAdminStatus {
  provider_id: string
  provider_type?: string | null
  configured: boolean
  running: boolean
  enabled: boolean
  info?: ProviderInfo | null
  config?: ProviderConfigSummary | null
}

export interface ProviderOperationResult {
  action: string
  provider_id: string
  accepted: boolean
  detail?: string | null
  status?: ProviderAdminStatus | null
}

export interface ProviderConnectionCheckResult {
  provider_id: string
  ok: boolean
  detail?: string | null
  models: ProviderModel[]
}

export interface ContentPart {
  type: string
  text?: string | null
  url?: string | null
  data?: string | null
  mime_type?: string | null
  detail?: string | null
  metadata?: Record<string, unknown>
}

export interface Message {
  role: string
  content?: ContentPart[] | null
  name?: string | null
  tool_call_id?: string | null
  tool_calls?: ToolCall[] | null
  metadata?: Record<string, unknown>
}

export interface ToolCall {
  id: string
  name: string
  arguments?: string | null
}

export interface ToolResult {
  call_id: string
  name: string
  content?: string | null
  success: boolean
  error?: string | null
  requires_replan?: boolean
  metadata?: Record<string, unknown>
}

export interface ChatProviderResponse {
  provider_id: string
  model: string
  message?: Message | null
  tool_calls?: ToolCall[] | null
  finish_reason?: string | null
  usage?: unknown
  raw?: unknown
}

export interface ChatResponse {
  response: ChatProviderResponse
  context_snapshot?: unknown
  tool_results?: ToolResult[]
  completed?: boolean
  stop_reason?: string
  metadata?: Record<string, unknown>
}

export interface AgentStep {
  index: number
  request?: unknown
  response?: ChatProviderResponse | null
  tool_calls?: ToolCall[]
  tool_results?: ToolResult[]
  metadata?: Record<string, unknown>
}

export interface AgentRunResponse {
  response: ChatProviderResponse
  steps: AgentStep[]
  plan?: unknown
  skill_bundle?: unknown
  context_snapshot?: unknown
  completed: boolean
  stop_reason: string
  metadata?: Record<string, unknown>
}

export interface PluginDefinition {
  plugin_id: string
  name?: string | null
  version: string
  description?: string | null
  enabled: boolean
  metadata?: Record<string, unknown>
}

export interface PluginStatusReport {
  plugin_id: string
  status: string
  reason?: string | null
  metadata?: Record<string, unknown>
}

export interface PluginCommandDefinition {
  plugin_id: string
  name: string
  usage?: string | null
  description?: string | null
  aliases?: string[]
  enabled?: boolean
}

const API_BASE = import.meta.env.VITE_CYRENE_API_BASE_URL ?? ''

export async function checkHealth() {
  return request<{ status: string }>('/health')
}

export async function checkReady() {
  return request<{ status: string }>('/ready', { allowErrorBody: true })
}

export async function login(username: string, password: string) {
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)
  return request<{ authenticated: boolean }>('/auth/login', {
    method: 'POST',
    body,
  })
}

export async function logout() {
  return request<{ authenticated: boolean }>('/auth/logout', { method: 'POST' })
}

export async function listProviderStatuses() {
  return request<{ providers: ProviderAdminStatus[] }>('/providers/statuses')
}

export async function listProviderCatalog() {
  return request<{ providers: ProviderInfo[] }>('/providers/catalog')
}

export async function listProviderConfigs() {
  return request<{ configs: ProviderConfigSummary[] }>('/providers/configs')
}

export async function listProviderModels(providerId: string) {
  return request<{ models: ProviderModel[] }>(
    `/providers/${encodeURIComponent(providerId)}/models`
  )
}

export async function startProvider(providerId: string) {
  return providerAction(providerId, 'start')
}

export async function stopProvider(providerId: string) {
  return providerAction(providerId, 'stop')
}

export async function reloadProvider(providerId: string) {
  return providerAction(providerId, 'reload')
}

export async function checkProvider(providerId: string) {
  return request<ProviderConnectionCheckResult>(
    `/providers/${encodeURIComponent(providerId)}/check`,
    { method: 'POST' }
  )
}

export async function chat(body: Record<string, unknown>) {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    json: body,
  })
}

// 编排层流式事件，与后端 ChatStreamEvent 对应。
export interface ChatStreamEvent {
  type: 'delta' | 'tool_call' | 'tool_result' | 'done' | 'error'
  delta_text?: string | null
  reasoning_delta?: string | null
  tool_calls?: ToolCall[]
  tool_results?: ToolResult[]
  content?: string | null
  finish_reason?: string | null
  usage?: unknown
  detail?: string | null
  metadata?: Record<string, unknown>
}

export interface ChatStreamHandlers {
  onDelta?: (text: string, reasoning?: string | null) => void
  onToolCall?: (calls: ToolCall[]) => void
  onToolResult?: (results: ToolResult[]) => void
  onDone?: (event: ChatStreamEvent) => void
  onError?: (detail: string) => void
}

// 通过 SSE 逐事件读取 /chat/stream。
// 用 fetch + ReadableStream，按空行切分 SSE frame，解析 data: 行的 JSON。
export async function chatStream(
  body: Record<string, unknown>,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    credentials: 'include',
    signal,
  })

  if (!response.ok || !response.body) {
    const payload = await parsePayload(response)
    const message = extractErrorMessage(payload) || response.statusText
    throw new ApiError(response.status, message, payload)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (event: ChatStreamEvent) => {
    switch (event.type) {
      case 'delta':
        if (event.delta_text || event.reasoning_delta) {
          handlers.onDelta?.(event.delta_text ?? '', event.reasoning_delta)
        }
        break
      case 'tool_call':
        handlers.onToolCall?.(event.tool_calls ?? [])
        break
      case 'tool_result':
        handlers.onToolResult?.(event.tool_results ?? [])
        break
      case 'done':
        handlers.onDone?.(event)
        break
      case 'error':
        {
          const detail = event.detail || '流式输出失败'
          handlers.onError?.(detail)
          throw new ApiError(0, detail, { detail })
        }
    }
  }

  // 解析缓冲区里完整的 SSE frame（以空行分隔），保留未完成的尾部。
  const flushFrames = () => {
    let separator = buffer.indexOf('\n\n')
    while (separator !== -1) {
      const frame = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      const dataLine = frame
        .split('\n')
        .find((line) => line.startsWith('data:'))
      if (dataLine) {
        const raw = dataLine.slice(5).trim()
        if (raw) {
          let event: ChatStreamEvent
          try {
            event = JSON.parse(raw) as ChatStreamEvent
          } catch {
            // 跳过无法解析的 frame，保持流不中断。
            separator = buffer.indexOf('\n\n')
            continue
          }
          dispatch(event)
        }
      }
      separator = buffer.indexOf('\n\n')
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    flushFrames()
  }
  buffer += decoder.decode()
  flushFrames()
}

export async function runAgent(body: Record<string, unknown>) {
  return request<AgentRunResponse>('/agents/run', {
    method: 'POST',
    json: body,
  })
}

export interface GeneratedImage {
  index: number
  url?: string | null
  b64_json?: string | null
  mime_type?: string | null
  revised_prompt?: string | null
  metadata?: Record<string, unknown>
}

export interface ImageGenerationResponse {
  provider_id: string
  model?: string | null
  images: GeneratedImage[]
  raw?: unknown
}

export interface ImageGenerationResult {
  response: ImageGenerationResponse
  metadata?: Record<string, unknown>
}

export async function generateImage(body: Record<string, unknown>) {
  return request<ImageGenerationResult>('/images/generate', {
    method: 'POST',
    json: body,
  })
}

export async function listPlugins() {
  return request<{ plugins: PluginDefinition[] }>('/plugins')
}

export async function listPluginStatuses() {
  return request<{ statuses: PluginStatusReport[] }>('/plugins/statuses')
}

export async function listPluginCommands() {
  return request<{ commands: PluginCommandDefinition[] }>('/plugins/commands')
}

export async function enablePlugin(pluginId: string) {
  return pluginAction(pluginId, 'enable')
}

export async function disablePlugin(pluginId: string) {
  return pluginAction(pluginId, 'disable')
}

export async function reloadPlugin(pluginId: string) {
  return pluginAction(pluginId, 'reload')
}

async function providerAction(providerId: string, action: string) {
  return request<ProviderOperationResult>(
    `/providers/${encodeURIComponent(providerId)}/${action}`,
    { method: 'POST' }
  )
}

async function pluginAction(pluginId: string, action: string) {
  return request<PluginDefinition | { accepted: boolean; detail?: string }>(
    `/plugins/${encodeURIComponent(pluginId)}/${action}`,
    { method: 'POST' }
  )
}

async function request<T>(
  path: string,
  options: RequestInit & {
    json?: unknown
    allowErrorBody?: boolean
  } = {}
): Promise<T> {
  const headers = new Headers(options.headers)
  let body = options.body

  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(options.json)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    body,
    headers,
    credentials: 'include',
  })
  const payload = await parsePayload(response)

  if (!response.ok) {
    const message = extractErrorMessage(payload) || response.statusText
    if (options.allowErrorBody) {
      return payload as T
    }
    throw new ApiError(response.status, message, payload)
  }

  return payload as T
}

async function parsePayload(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function extractErrorMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(String).join(', ')
  return null
}
