"""Print the settings this install would run with (no keys): its folders, its chat identity and its region.
Usage: uv run python scripts/show_settings.py   (set ODIE_HOME or ODIE_DATA_DIR / ODIE_CONFIG_DIR to check a copy)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from odie import config  # noqa: E402

s = config.settings
for key in ("home", "data_dir", "config_dir", "memory_file", "app_name", "user_id", "timezone", "locale", "country",
            "currency", "addons_dirs", "model_id", "host", "port"):
    print(f"{key:16} {getattr(s, key)}")
print(f"{'public_url':16} {'set' if s.public_url != 'http://localhost:8000' else 'default'}")
