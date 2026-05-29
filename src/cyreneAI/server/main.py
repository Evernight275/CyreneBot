from __future__ import annotations

import asyncio

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.server.app import create_app
from cyreneAI.server.config import (
    build_bot_polling_state_database_path_from_env,
    build_context_database_path_from_env,
    build_disabled_plugin_ids_from_env,
    build_plugin_paths_from_env,
    build_plugin_storage_path_from_env,
    build_plugin_task_database_path_from_env,
    build_provider_configs_from_env,
    build_server_settings_from_env,
    build_telegram_bot_token_from_env,
    build_telegram_polling_enabled_from_env,
    build_telegram_polling_interval_seconds_from_env,
    build_telegram_polling_limit_from_env,
    build_telegram_polling_timeout_seconds_from_env,
    build_telegram_webhook_model_from_env,
    build_telegram_webhook_provider_id_from_env,
    build_telegram_webhook_secret_from_env,
)
from cyreneAI.infra.adapters.plugins.filesystem import (
    FileSystemPluginAssets,
    FileSystemPluginLoader,
)


def _build_app():
    plugin_assets = FileSystemPluginAssets()
    return create_app(
        asyncio.run(
            build_cyrene_ai_runtime(
                provider_configs=build_provider_configs_from_env(),
                context_database_path=build_context_database_path_from_env(),
                telegram_bot_token=build_telegram_bot_token_from_env(),
                bot_polling_state_database_path=build_bot_polling_state_database_path_from_env(),
                plugin_storage_path=build_plugin_storage_path_from_env(),
                plugin_task_database_path=build_plugin_task_database_path_from_env(),
                disabled_plugin_ids=build_disabled_plugin_ids_from_env(),
                plugin_fail_fast=False,
                plugin_assets=plugin_assets,
                plugin_loaders=[
                    FileSystemPluginLoader(path, plugin_assets=plugin_assets)
                    for path in build_plugin_paths_from_env()
                ],
            )
        ),
        settings=build_server_settings_from_env(),
        telegram_webhook_secret=build_telegram_webhook_secret_from_env(),
        telegram_provider_id=build_telegram_webhook_provider_id_from_env(),
        telegram_model=build_telegram_webhook_model_from_env(),
        telegram_polling_enabled=build_telegram_polling_enabled_from_env(),
        telegram_polling_interval_seconds=build_telegram_polling_interval_seconds_from_env(),
        telegram_polling_timeout_seconds=build_telegram_polling_timeout_seconds_from_env(),
        telegram_polling_limit=build_telegram_polling_limit_from_env(),
    )


app = _build_app()
