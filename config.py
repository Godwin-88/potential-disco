# Root-level re-export so all modules can use `from config import get_settings`
from core.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
