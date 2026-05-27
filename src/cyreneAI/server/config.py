from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv

from cyreneAI.core.schema.provider import ProviderConfig, ProviderType


def build_provider_configs_from_env() -> list[ProviderConfig]:
    load_dotenv()

    configs: list[ProviderConfig] = []
    timeout = timedelta(seconds=int(os.getenv("CYRENE_PROVIDER_TIMEOUT_SECONDS", "60")))

    openai_compatible_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    if openai_compatible_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv(
                    "OPENAI_COMPATIBLE_PROVIDER_ID",
                    "openai-compatible",
                ),
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key=openai_compatible_key,
                base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL")
                or os.getenv("OPENAI_BASE_URL"),
                timeout=timeout,
            )
        )

    openai_responses_key = os.getenv("OPENAI_RESPONSES_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    if openai_responses_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv("OPENAI_RESPONSES_PROVIDER_ID", "openai"),
                provider_type=ProviderType.OPENAI_RESPONSES,
                api_key=openai_responses_key,
                base_url=os.getenv("OPENAI_RESPONSES_BASE_URL")
                or os.getenv("OPENAI_BASE_URL"),
                timeout=timeout,
            )
        )

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv("ANTHROPIC_PROVIDER_ID", "anthropic"),
                provider_type=ProviderType.ANTHROPIC,
                api_key=anthropic_key,
                base_url=os.getenv("ANTHROPIC_BASE_URL"),
                timeout=timeout,
            )
        )

    google_key = os.getenv("GOOGLE_GENAI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if google_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv("GOOGLE_GENAI_PROVIDER_ID", "google"),
                provider_type=ProviderType.GOOGLE,
                api_key=google_key,
                base_url=os.getenv("GOOGLE_GENAI_BASE_URL")
                or os.getenv("GOOGLE_BASE_URL"),
                timeout=timeout,
            )
        )

    return configs
