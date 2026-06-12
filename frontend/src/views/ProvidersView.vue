<script setup lang="ts">
import { Play, RefreshCw, ShieldCheck, Square } from '@lucide/vue'

import { useProviders } from '../composables/useProviders'

const {
  providers,
  providerCatalog,
  providersLoading,
  selectedProviderId,
  selectedProvider,
  selectedProviderModels,
  selectedProviderModelError,
  providerSummary,
  refreshProviders,
  setProvider,
  configFor,
  operateProvider,
} = useProviders()
</script>

<template>
  <section class="provider-admin-view">
    <div class="management-hero">
      <div>
        <h2>供应商统一管理</h2>
        <p>集中查看配置、运行状态、模型列表和连接操作。</p>
      </div>
      <button class="tool-button" type="button" @click="refreshProviders">
        <RefreshCw :size="16" :class="{ spin: providersLoading }" />
        刷新供应商
      </button>
    </div>

    <section class="metric-strip">
      <div class="metric">
        <span>供应商</span>
        <strong>{{ providerSummary.total }}</strong>
      </div>
      <div class="metric">
        <span>已配置</span>
        <strong>{{ providerSummary.configured }}</strong>
      </div>
      <div class="metric">
        <span>运行中</span>
        <strong>{{ providerSummary.running }}</strong>
      </div>
      <div class="metric">
        <span>模型</span>
        <strong>{{ selectedProviderModels.length }}</strong>
      </div>
    </section>

    <div class="provider-admin-grid">
      <article class="panel provider-list-panel">
        <div class="panel-heading">
          <div>
            <h2>实例</h2>
            <p>选择一个供应商作为当前全局调用目标。</p>
          </div>
        </div>

        <div class="table-list">
          <div
            v-for="provider in providers"
            :key="provider.provider_id"
            class="provider-row"
            :class="{ selected: provider.provider_id === selectedProviderId }"
            @click="setProvider(provider.provider_id)"
          >
            <div class="row-main">
              <span class="status-dot" :class="provider.running ? 'ready' : 'not_ready'" />
              <div>
                <strong>{{ provider.provider_id }}</strong>
                <span>{{ provider.provider_type || provider.info?.provider_type || '未知类型' }}</span>
              </div>
            </div>
            <div class="badge-group">
              <span class="badge" :class="{ ok: provider.configured }">
                {{ provider.configured ? '已配置' : '缺少配置' }}
              </span>
              <span class="badge" :class="{ ok: provider.running }">
                {{ provider.running ? '运行中' : '已停止' }}
              </span>
            </div>
            <div class="row-actions">
              <button class="icon-button" type="button" title="启动" @click.stop="operateProvider(provider.provider_id, 'start')">
                <Play :size="16" />
              </button>
              <button class="icon-button" type="button" title="停止" @click.stop="operateProvider(provider.provider_id, 'stop')">
                <Square :size="16" />
              </button>
              <button class="icon-button" type="button" title="重载" @click.stop="operateProvider(provider.provider_id, 'reload')">
                <RefreshCw :size="16" />
              </button>
              <button class="icon-button" type="button" title="检查连接" @click.stop="operateProvider(provider.provider_id, 'check')">
                <ShieldCheck :size="16" />
              </button>
            </div>
          </div>
        </div>
      </article>

      <aside class="provider-side">
        <article class="panel">
          <div class="panel-heading compact">
            <div>
              <h2>当前目标</h2>
              <p>{{ selectedProviderId || '尚未选择供应商' }}</p>
            </div>
          </div>
          <dl class="detail-list" v-if="selectedProvider">
            <div>
              <dt>类型</dt>
              <dd>{{ selectedProvider.provider_type || selectedProvider.info?.provider_type }}</dd>
            </div>
            <div>
              <dt>运行中</dt>
              <dd>{{ selectedProvider.running ? '是' : '否' }}</dd>
            </div>
            <div>
              <dt>启用</dt>
              <dd>{{ selectedProvider.enabled ? '是' : '否' }}</dd>
            </div>
            <div>
              <dt>API 密钥</dt>
              <dd>{{ configFor(selectedProvider.provider_id)?.has_api_key ? '已保存' : '未保存' }}</dd>
            </div>
            <div>
              <dt>基础 URL</dt>
              <dd>{{ configFor(selectedProvider.provider_id)?.base_url || '默认' }}</dd>
            </div>
          </dl>
        </article>

        <article class="panel">
          <div class="panel-heading compact">
            <div>
              <h2>可用模型</h2>
              <p>{{ selectedProviderModels.length }} 个模型</p>
            </div>
          </div>
          <div class="compact-list">
            <div v-if="selectedProviderModelError" class="error-state">
              <strong>模型加载失败</strong>
              <span>{{ selectedProviderModelError }}</span>
            </div>
            <div v-else-if="selectedProviderModels.length === 0">
              <strong>暂无模型</strong>
              <span>选择运行中的供应商后刷新模型。</span>
            </div>
            <div v-for="model in selectedProviderModels" :key="model.model_id">
              <strong>{{ model.name || model.model_id }}</strong>
              <span>{{ model.model_id }}</span>
            </div>
          </div>
        </article>
      </aside>
    </div>

    <article class="panel provider-catalog-panel">
      <div class="panel-heading compact">
        <div>
          <h2>供应商目录</h2>
          <p>{{ providerCatalog.length }} 种供应商类型</p>
        </div>
      </div>
      <div class="catalog-grid">
        <div v-for="item in providerCatalog" :key="item.provider_type" class="catalog-card">
          <strong>{{ item.name }}</strong>
          <span>{{ item.provider_type }}</span>
          <small>{{ item.description || '暂无描述' }}</small>
          <div class="capability-row">
            <span v-for="capability in item.capabilities || []" :key="capability" class="badge ok">
              {{ capability }}
            </span>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>
