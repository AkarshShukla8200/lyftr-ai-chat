"""Production ASGI entrypoint: `uvicorn app.server:app --workers 1`.

Kept separate from main.py so importing the app factory in tests never reads
the real environment or touches the real cache/database.
"""

from __future__ import annotations

import logging

import litellm

from .config import Settings
from .llm_gateway import LiteLLMGateway, configure_cache
from .main import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# LiteLLM verbose/debug output off; only warnings and above.
litellm.suppress_debug_info = True
litellm.set_verbose = False
for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
    logging.getLogger(name).setLevel(logging.WARNING)

settings = Settings.from_env()
try:
    configure_cache(settings.llm_cache_dir)
except OSError as exc:
    # Keep serving so the UI can show errors; /health reports "cache not enabled" (503).
    logging.getLogger("app").error("cache init failed: %s", type(exc).__name__)
app = create_app(settings, LiteLLMGateway(settings))
