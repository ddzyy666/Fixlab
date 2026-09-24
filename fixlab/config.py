"""Local TOML configuration, with optional environment overrides."""
import os
import tomllib
from pathlib import Path


def load_config(path="fixlab.local.toml", model=None):
    config_path = Path(path)
    data = {}
    if config_path.exists():
        try:
            with config_path.open("rb") as stream:
                data = tomllib.load(stream)
        except tomllib.TOMLDecodeError:
            raise ValueError("Invalid TOML in configuration file") from None
    values = {
        "model": model or os.getenv("FIXLAB_MODEL") or data.get("model"),
        "api_key": os.getenv("FIXLAB_API_KEY") or data.get("api_key"),
        "api_base": os.getenv("FIXLAB_API_BASE") or data.get("api_base") or "https://api.openai.com/v1",
    }
    for name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Configure {name} in {config_path} or its FIXLAB environment variable")
    return values
