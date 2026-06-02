from __future__ import annotations

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.server.app import create_app_with_runtime_builder
from cyreneAI.server.config import (
    build_bot_admin_config_from_env,
    build_bot_polling_state_database_path_from_env,
    build_context_database_path_from_env,
    build_disabled_plugin_ids_from_env,
    build_mcp_stdio_servers_from_env,
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
    build_tool_sandbox_commands_from_env,
    build_tool_sandbox_mode_from_env,
    build_tool_sandbox_timeout_seconds_from_env,
    build_vector_database_path_from_env,
    build_web_search_api_key_from_env,
    build_web_search_api_key_header_from_env,
    build_web_search_timeout_seconds_from_env,
    build_web_search_url_template_from_env,
)


async def _build_runtime():
    return await build_cyrene_ai_runtime(
        provider_configs=build_provider_configs_from_env(),
        context_database_path=build_context_database_path_from_env(),
        vector_database_path=build_vector_database_path_from_env(),
        tool_sandbox_mode=build_tool_sandbox_mode_from_env(),
        tool_sandbox_commands=build_tool_sandbox_commands_from_env(),
        tool_sandbox_timeout_seconds=build_tool_sandbox_timeout_seconds_from_env(),
        mcp_stdio_servers=build_mcp_stdio_servers_from_env(),
        web_search_url_template=build_web_search_url_template_from_env(),
        web_search_api_key=build_web_search_api_key_from_env(),
        web_search_api_key_header=build_web_search_api_key_header_from_env(),
        web_search_timeout_seconds=build_web_search_timeout_seconds_from_env(),
        telegram_bot_token=build_telegram_bot_token_from_env(),
        bot_polling_state_database_path=build_bot_polling_state_database_path_from_env(),
        bot_admin_config=build_bot_admin_config_from_env(),
        plugin_storage_path=build_plugin_storage_path_from_env(),
        plugin_task_database_path=build_plugin_task_database_path_from_env(),
        disabled_plugin_ids=build_disabled_plugin_ids_from_env(),
        plugin_fail_fast=False,
        plugin_paths=build_plugin_paths_from_env(),
    )


def _build_app():
    return create_app_with_runtime_builder(
        _build_runtime,
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
