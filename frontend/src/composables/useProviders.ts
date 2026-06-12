import { computed, ref } from 'vue'

import {
  checkProvider,
  listProviderCatalog,
  listProviderConfigs,
  listProviderModels,
  listProviderStatuses,
  reloadProvider,
  startProvider,
  stopProvider,
  type ProviderAdminStatus,
  type ProviderConfigSummary,
  type ProviderInfo,
  type ProviderModel,
} from '../api'
import { actionLabel } from '../utils/format'
import { useNotify } from './useNotify'

const providers = ref<ProviderAdminStatus[]>([])
const providerCatalog = ref<ProviderInfo[]>([])
const providerConfigs = ref<ProviderConfigSummary[]>([])
const providerModels = ref<Record<string, ProviderModel[]>>({})
const providerModelErrors = ref<Record<string, string>>({})
const selectedProviderId = ref('')
const selectedModel = ref('')
const providersLoading = ref(false)

const selectedProvider = computed(() =>
  providers.value.find((provider) => provider.provider_id === selectedProviderId.value)
)

const selectedProviderModels = computed(() => {
  if (!selectedProviderId.value) return []
  return providerModels.value[selectedProviderId.value] ?? []
})

const selectedProviderModelError = computed(() => {
  if (!selectedProviderId.value) return ''
  return providerModelErrors.value[selectedProviderId.value] ?? ''
})

const runnableProviders = computed(() =>
  providers.value.filter((provider) => provider.running || provider.configured)
)

const providerSummary = computed(() => {
  const running = providers.value.filter((provider) => provider.running).length
  const configured = providers.value.filter((provider) => provider.configured).length
  return { running, configured, total: providers.value.length }
})

const { showToast, showApiError } = useNotify()

function ensureProviderSelection() {
  if (
    selectedProviderId.value &&
    providers.value.some((provider) => provider.provider_id === selectedProviderId.value)
  ) {
    return
  }
  const preferred = providers.value.find((provider) => provider.running)
  selectedProviderId.value =
    preferred?.provider_id ?? providers.value[0]?.provider_id ?? ''
  selectedModel.value = ''
}

function ensureModelSelection(models: ProviderModel[]) {
  if (models.some((model) => model.model_id === selectedModel.value)) return
  selectedModel.value = models[0]?.model_id ?? ''
}

function configuredModelsFor(providerId: string) {
  const statusModels =
    providers.value.find((provider) => provider.provider_id === providerId)?.config
      ?.models ?? []
  if (statusModels.length > 0) return normalizeProviderModels(statusModels)
  return normalizeProviderModels(configFor(providerId)?.models ?? [])
}

function normalizeProviderModels(models: ProviderModel[]) {
  const normalized: ProviderModel[] = []
  const seen = new Set<string>()
  for (const model of models) {
    const modelId = model.model_id.trim()
    if (!modelId || seen.has(modelId)) continue
    seen.add(modelId)
    normalized.push({ ...model, model_id: modelId })
  }
  return normalized
}

async function refreshSelectedProviderModels() {
  if (!selectedProviderId.value) return
  const providerId = selectedProviderId.value
  try {
    const result = await listProviderModels(providerId)
    const models = normalizeProviderModels(result.models)
    providerModels.value = {
      ...providerModels.value,
      [providerId]: models,
    }
    providerModelErrors.value = {
      ...providerModelErrors.value,
      [providerId]: '',
    }
    ensureModelSelection(models)
  } catch (error) {
    const fallbackModels = configuredModelsFor(providerId)
    providerModels.value = {
      ...providerModels.value,
      [providerId]: fallbackModels,
    }
    providerModelErrors.value = {
      ...providerModelErrors.value,
      [providerId]:
        error instanceof Error ? error.message : '供应商模型列表加载失败',
    }
    ensureModelSelection(fallbackModels)
    showApiError(error, '供应商模型列表加载失败')
  }
}

async function refreshProviders() {
  providersLoading.value = true
  try {
    const [statuses, catalog, configs] = await Promise.all([
      listProviderStatuses(),
      listProviderCatalog(),
      listProviderConfigs(),
    ])
    providers.value = statuses.providers
    providerCatalog.value = catalog.providers
    providerConfigs.value = configs.configs
    ensureProviderSelection()
    await refreshSelectedProviderModels()
  } catch (error) {
    showApiError(error, '供应商刷新失败')
  } finally {
    providersLoading.value = false
  }
}

function setProvider(providerId: string) {
  selectedProviderId.value = providerId
  selectedModel.value = ''
  void refreshSelectedProviderModels()
}

function configFor(providerId: string) {
  return (
    providerConfigs.value.find((config) => config.provider_id === providerId) ??
    providers.value.find((provider) => provider.provider_id === providerId)?.config ??
    undefined
  )
}

async function operateProvider(
  providerId: string,
  action: 'start' | 'stop' | 'reload' | 'check'
) {
  try {
    if (action === 'start') await startProvider(providerId)
    if (action === 'stop') await stopProvider(providerId)
    if (action === 'reload') await reloadProvider(providerId)
    if (action === 'check') {
      const result = await checkProvider(providerId)
      showToast(result.ok ? 'success' : 'error', result.detail ?? '供应商检查完成')
    } else {
      showToast('success', `供应商${actionLabel(action)}已提交`)
    }
    await refreshProviders()
  } catch (error) {
    showApiError(error, `供应商${actionLabel(action)}失败`)
  }
}

export function useProviders() {
  return {
    providers,
    providerCatalog,
    providerConfigs,
    providerModels,
    providerModelErrors,
    selectedProviderId,
    selectedModel,
    providersLoading,
    selectedProvider,
    selectedProviderModels,
    selectedProviderModelError,
    runnableProviders,
    providerSummary,
    refreshProviders,
    refreshSelectedProviderModels,
    setProvider,
    configFor,
    operateProvider,
  }
}
