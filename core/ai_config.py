"""AI provider/model configuration system."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("core.ai_config")

_CONFIG_DIR = Path("config")
_PROVIDERS_PATH = _CONFIG_DIR / "providers.json"
_MODELS_PATH = _CONFIG_DIR / "models.json"
_PROMPTS_DIR = _CONFIG_DIR / "prompts"


class ProviderConfig:
    endpoint: str
    env_key: str

    def __init__(self, data: dict) -> None:
        self.endpoint = data["endpoint"].rstrip("/")
        self.env_key = data["env_key"]

    @classmethod
    def from_dict(cls, data: dict) -> ProviderConfig:
        return cls(data)


class ModelConfig:
    provider: str
    model: str
    vision: bool
    endpoint_type: str

    def __init__(self, data: dict) -> None:
        self.provider = data["provider"]
        self.model = data["model"]
        self.vision = data.get("vision", False)
        self.endpoint_type = data.get("endpoint_type", "responses")

    @classmethod
    def from_dict(cls, data: dict) -> ModelConfig:
        return cls(data)


class AiConfig:
    """Loads and caches provider/model/prompt configuration."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}
        self._models: dict[str, ModelConfig] = {}
        self._prompts: dict[str, str] = {}
        self._loaded = False

    def load(self) -> None:
        self._providers.clear()
        self._models.clear()
        self._prompts.clear()

        if _PROVIDERS_PATH.exists():
            try:
                data = json.loads(_PROVIDERS_PATH.read_text())
                for name, cfg in data.items():
                    self._providers[name] = ProviderConfig.from_dict(cfg)
                log.info("Loaded %d providers", len(self._providers))
            except Exception as e:
                log.warning("Failed to load providers.json: %s", e)

        if _MODELS_PATH.exists():
            try:
                data = json.loads(_MODELS_PATH.read_text())
                for name, cfg in data.items():
                    self._models[name] = ModelConfig.from_dict(cfg)
                log.info("Loaded %d models", len(self._models))
            except Exception as e:
                log.warning("Failed to load models.json: %s", e)

        self._loaded = True

    def reload(self) -> None:
        self._loaded = False
        self.load()

    def get_model(self, name: str) -> ModelConfig | None:
        if not self._loaded:
            self.load()
        return self._models.get(name)

    def get_provider(self, name: str) -> ProviderConfig | None:
        if not self._loaded:
            self.load()
        return self._providers.get(name)

    def get_prompt(self, endpoint_type: str) -> str:
        cached = self._prompts.get(endpoint_type)
        if cached is not None:
            return cached
        path = _PROMPTS_DIR / f"scam_{endpoint_type}.txt"
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            self._prompts[endpoint_type] = text
            return text
        log.warning("Prompt file not found: %s", path)
        fallback = "Detect crypto scam in this message."
        self._prompts[endpoint_type] = fallback
        return fallback

    def resolve_model(self, model_name: str) -> tuple[ModelConfig | None, ProviderConfig | None, str]:
        """Resolve model config, provider, and prompt for a model name."""
        mc = self.get_model(model_name)
        if not mc:
            return None, None, ""
        pc = self.get_provider(mc.provider)
        if not pc:
            return None, None, ""
        prompt = self.get_prompt(mc.endpoint_type)
        return mc, pc, prompt


ai_config = AiConfig()
