<script setup lang="ts">
import { Bot, Image as ImageIcon, RotateCcw, TriangleAlert, X } from '@lucide/vue'

import { useFeed, type FeedItem } from '../composables/useFeed'
import { contentToText, imageSrc } from '../utils/format'

defineProps<{ item: FeedItem }>()

const { previewImage, retryItem, dismissItem } = useFeed()

const roleLabel = (kind: FeedItem['kind']) =>
  kind === 'user'
    ? '用户'
    : kind === 'agent'
      ? 'Agent'
      : kind === 'images'
        ? '图像'
        : kind === 'error'
          ? '错误'
          : '助手'

const errorModeLabel = (mode: FeedItem['errorMode']) =>
  mode === 'agent' ? 'Agent 运行' : mode === 'image' ? '图像生成' : '对话请求'
</script>

<template>
  <div
    class="message-row"
    :class="item.kind === 'user' ? 'user' : item.kind === 'error' ? 'error' : 'assistant'"
  >
    <div class="message-avatar">
      <component v-if="item.kind === 'agent'" :is="Bot" :size="16" />
      <component v-else-if="item.kind === 'images'" :is="ImageIcon" :size="16" />
      <component v-else-if="item.kind === 'error'" :is="TriangleAlert" :size="16" />
      <template v-else>{{ item.kind === 'user' ? '我' : 'A' }}</template>
    </div>
    <div class="message-body">
      <div class="message-role">{{ roleLabel(item.kind) }}</div>

      <!-- 失败详情：留在消息流里，便于排查供应商/模型连通性 -->
      <div v-if="item.kind === 'error'" class="error-card">
        <div class="error-card-head">
          <span class="error-tag">{{ errorModeLabel(item.errorMode) }}失败</span>
          <span v-if="item.errorStatus" class="error-status">HTTP {{ item.errorStatus }}</span>
        </div>
        <div class="error-detail">{{ item.errorDetail }}</div>
        <div class="error-actions">
          <button class="error-retry" type="button" @click="retryItem(item)">
            <RotateCcw :size="13" />
            重试
          </button>
          <button class="error-dismiss" type="button" @click="dismissItem(item)">
            <X :size="13" />
            移除
          </button>
        </div>
      </div>

      <!-- 文本内容（user / assistant / agent 最终回复） -->
      <div v-else-if="item.content || item.pending" class="message-content">
        {{ item.content
        }}<span v-if="item.pending" class="stream-caret">▍</span>
      </div>

      <!-- 对话工具调用 -->
      <div v-if="item.toolCalls && item.toolCalls.length" class="tool-call-list">
        <div class="tool-call-title">工具调用</div>
        <div v-for="call in item.toolCalls" :key="call.id" class="tool-call-item">
          <strong>{{ call.name }}</strong>({{ call.arguments }})
        </div>
      </div>

      <!-- 对话工具结果：测模型时让工具调用的实际行为可见 -->
      <div v-if="item.toolResults && item.toolResults.length" class="tool-call-list">
        <div class="tool-call-title">工具结果</div>
        <div v-for="result in item.toolResults" :key="result.call_id" class="agent-tool-result">
          <div class="agent-tool-result-head">
            <span>{{ result.name }}</span>
            <span :class="result.success ? 'ok' : 'fail'">
              {{ result.success ? '成功' : '错误：' + result.error }}
            </span>
          </div>
          <pre>{{ result.content || result.error }}</pre>
        </div>
      </div>

      <!-- Agent 执行轨迹 -->
      <div v-if="item.agentSteps && item.agentSteps.length" class="agent-trace">
        <div v-for="step in item.agentSteps" :key="step.index" class="agent-step">
          <div class="agent-step-head">
            <span class="agent-step-index">步骤 {{ step.index }}</span>
            <span class="badge ok" v-if="step.response?.finish_reason">{{ step.response.finish_reason }}</span>
          </div>
          <div v-if="step.response?.message?.content" class="agent-thought">
            <div class="agent-block-label">思考 / 说明</div>
            <div>{{ contentToText(step.response.message.content) }}</div>
          </div>
          <div v-if="step.tool_calls && step.tool_calls.length" class="agent-block">
            <div class="agent-block-label">工具调用</div>
            <div v-for="call in step.tool_calls" :key="call.id" class="agent-tool-call">
              <span class="agent-tool-call-name">{{ call.name }}</span>({{ call.arguments }})
            </div>
          </div>
          <div v-if="step.tool_results && step.tool_results.length" class="agent-block">
            <div class="agent-block-label">工具结果</div>
            <div v-for="result in step.tool_results" :key="result.call_id" class="agent-tool-result">
              <div class="agent-tool-result-head">
                <span>调用 ID：{{ result.call_id }}</span>
                <span :class="result.success ? 'ok' : 'fail'">
                  {{ result.success ? '成功' : '错误：' + result.error }}
                </span>
              </div>
              <pre>{{ result.content || result.error }}</pre>
            </div>
          </div>
        </div>
      </div>

      <!-- 生成图库 -->
      <div v-if="item.images && item.images.length" class="image-gallery">
        <div v-for="(img, idx) in item.images" :key="idx" class="image-card" @click="previewImage = img">
          <img :src="imageSrc(img)" alt="生成结果" />
          <div class="image-card-overlay">
            <p>{{ img.revised_prompt || item.prompt }}</p>
          </div>
        </div>
      </div>

      <div class="chat-meta" v-if="item.time || item.model">
        <span v-if="item.time">{{ item.time }}</span>
        <span v-if="item.model">{{ item.model }}</span>
      </div>
    </div>
  </div>
</template>
