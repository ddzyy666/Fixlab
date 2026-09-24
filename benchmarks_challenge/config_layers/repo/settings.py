from merge import resolve
DEFAULTS = {"workers": 4, "logging": {"enabled": True, "level": "info"}, "tags": ["base"]}
def load_settings(file_config, overrides):
    return resolve(DEFAULTS,file_config,overrides)
