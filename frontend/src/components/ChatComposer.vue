<script setup lang="ts">
import { Bot, Image as ImageIcon, Loader2, Send } from '@lucide/vue'

import { composerModes, useFeed } from '../composables/useFeed'

const presets = [
  { label: '赛博朋克', text: 'cyberpunk style, neon glowing lights' },
  { label: '写实', text: 'photorealistic, 8k resolution, highly detailed' },
  { label: '动漫', text: 'anime style, vibrant colors, studio ghibli aesthetic' },
  { label: '3D 渲染', text: '3D render, octane render, soft lighting, clay style' },
  { label: '极简', text: 'minimalist vector art, clean lines, flat colors' },
]

const {
  composerMode,
  submitting,
  feed,
  chatForm,
  agentForm,
  imageForm,
  composerFooter,
  clearFeed,
  submitComposer,
  addPreset,
} = useFeed()
</script>

<template>
  <form class="composer" @submit.prevent="submitComposer">
    <div class="composer-modes">
      <button
        v-for="mode in composerModes"
        :key="mode.key"
        type="button"
        class="composer-mode"
        :class="{ active: composerMode === mode.key }"
        @click="composerMode = mode.key"
      >
        <component :is="mode.icon" :size="15" />
        {{ mode.label }}
      </button>
    </div>

    <!-- 对话模式参数 -->
    <div v-if="composerMode === 'chat'" class="composer-options">
      <label>
        系统提示
        <input v-model="chatForm.system" type="text" placeholder="可选，例如：用简洁中文回答" />
      </label>
      <label>
        温度
        <input v-model="chatForm.temperature" type="number" step="0.1" placeholder="默认" />
      </label>
      <label>
        最大 token
        <input v-model="chatForm.maxTokens" type="number" placeholder="默认" />
      </label>
    </div>

    <!-- Agent 模式参数 -->
    <div v-else-if="composerMode === 'agent'" class="composer-options agent-options">
      <label>
        最大步数
        <input v-model.number="agentForm.maxSteps" type="number" min="1" />
      </label>
      <label>
        每步工具
        <input v-model="agentForm.maxToolCallsPerStep" type="number" placeholder="默认" />
      </label>
      <label>
        工具总数
        <input v-model="agentForm.maxTotalToolCalls" type="number" placeholder="默认" />
      </label>
      <div class="composer-toggles">
        <label class="mini-check"><input v-model="agentForm.planningEnabled" type="checkbox" /> 规划</label>
        <label class="mini-check"><input v-model="agentForm.replanningEnabled" type="checkbox" /> 重新规划</label>
        <label class="mini-check"><input v-model="agentForm.memoryEnabled" type="checkbox" /> 记忆</label>
      </div>
    </div>

    <!-- 图像模式参数 -->
    <div v-else class="composer-options">
      <label>
        数量
        <select v-model.number="imageForm.count">
          <option :value="1">1</option>
          <option :value="2">2</option>
          <option :value="3">3</option>
          <option :value="4">4</option>
        </select>
      </label>
      <label>
        尺寸
        <select v-model="imageForm.size">
          <option value="256x256">256x256</option>
          <option value="512x512">512x512</option>
          <option value="1024x1024">1024x1024</option>
        </select>
      </label>
      <label>
        质量
        <select v-model="imageForm.quality">
          <option value="standard">标准</option>
          <option value="hd">HD</option>
        </select>
      </label>
      <label>
        格式
        <select v-model="imageForm.responseFormat">
          <option value="b64_json">Base64 JSON</option>
          <option value="url">URL</option>
        </select>
      </label>
    </div>

    <div class="composer-box">
      <textarea
        v-if="composerMode === 'chat'"
        v-model="chatForm.prompt"
        rows="1"
        placeholder="给 CyreneBot 发送消息"
        @keydown.enter.ctrl.prevent="submitComposer"
      />
      <textarea
        v-else-if="composerMode === 'agent'"
        v-model="agentForm.goal"
        rows="1"
        placeholder="描述 Agent 应该达成的目标"
        @keydown.enter.ctrl.prevent="submitComposer"
      />
      <textarea
        v-else
        v-model="imageForm.prompt"
        rows="1"
        placeholder="描述想要生成的画面"
        @keydown.enter.ctrl.prevent="submitComposer"
      />
      <div class="composer-actions">
        <template v-if="composerMode === 'chat'">
          <label class="mini-check">
            <input v-model="chatForm.stream" type="checkbox" />
            流式
          </label>
          <label class="mini-check">
            <input v-model="chatForm.allowTools" type="checkbox" />
            工具
          </label>
          <input
            v-model.number="chatForm.maxToolRounds"
            class="tool-rounds-input"
            type="number"
            min="0"
            title="工具轮次"
          />
        </template>
        <button class="send-button" type="submit" :disabled="submitting">
          <Loader2 v-if="submitting" :size="18" class="spin" />
          <Send v-else-if="composerMode === 'chat'" :size="18" />
          <Bot v-else-if="composerMode === 'agent'" :size="18" />
          <ImageIcon v-else :size="18" />
        </button>
      </div>
    </div>

    <div v-if="composerMode === 'image'" class="preset-prompts">
      <span
        v-for="preset in presets"
        :key="preset.label"
        class="preset-prompt-tag"
        @click="addPreset(preset.text)"
      >
        {{ preset.label }}
      </span>
    </div>

    <div class="composer-footer">
      <span>{{ composerFooter }}</span>
      <button v-if="feed.length" class="text-button" type="button" @click="clearFeed">清空</button>
    </div>
  </form>
</template>
