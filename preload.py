import asyncio
from pathlib import Path

from helpers import runtime, whisper, settings
from helpers.print_style import PrintStyle
from helpers import kokoro_tts
import models

# Phase 47.6 LD-8 — defense-in-depth assertion.
# Runs at module import time (before any async preload tasks).
# Guards against accidental re-introduction of capability-discovery walker code.
# Narrowed to _11_tools_prompt.py only per Pitfall 7.
from core.agents.boot_assertions import assert_no_filesystem_walkers

_REPO_ROOT = Path(__file__).parent
assert_no_filesystem_walkers(repo_root=_REPO_ROOT)


async def preload():
    try:
        set = settings.get_default_settings()

        # preload whisper model
        async def preload_whisper():
            try:
                return await whisper.preload(set["stt_model_size"])
            except Exception as e:
                PrintStyle().error(f"Error in preload_whisper: {e}")

        # preload embedding model
        async def preload_embedding():
            try:
                from plugins._model_config.helpers.model_config import get_embedding_model_config_object
                emb_cfg = get_embedding_model_config_object()
                if emb_cfg.provider.lower() == "huggingface":
                    emb_mod = models.get_embedding_model(
                        "huggingface", emb_cfg.name
                    )
                    emb_txt = await emb_mod.aembed_query("test")
                    return emb_txt
            except Exception as e:
                PrintStyle().error(f"Error in preload_embedding: {e}")

        # preload kokoro tts model if enabled
        async def preload_kokoro():
            if set["tts_kokoro"]:
                try:
                    return await kokoro_tts.preload()
                except Exception as e:
                    PrintStyle().error(f"Error in preload_kokoro: {e}")

        # async tasks to preload
        tasks = [
            preload_embedding(),
            # preload_whisper(),
            # preload_kokoro()
        ]

        await asyncio.gather(*tasks, return_exceptions=True)
        PrintStyle().print("Preload completed.")
    except Exception as e:
        PrintStyle().error(f"Error in preload: {e}")


async def _preload_recall_stack():
    """D-01 post-boot warm-up (fire-and-forget; never awaited on the boot path).

    Warms the process-singleton bge embedding model via the SAME
    ``BgeEmbeddingAdapter._get_model`` guard the recall path uses, so a user
    recall arriving mid-load blocks on ``_model_lock`` and reuses the in-flight
    load (D-02 single-flight). The load runs in a worker thread
    (``asyncio.to_thread``) so it never blocks the serving event loop. Warming
    is best-effort: any failure (e.g. a Qdrant hiccup) is logged, not raised, so
    it can never crash the serving loop.
    """
    try:
        from plugins._memory.backend.embedding_adapter import BgeEmbeddingAdapter

        # Same guard as the recall path -> single-flight (D-02); off the loop.
        await asyncio.to_thread(BgeEmbeddingAdapter._get_model)
        PrintStyle().print("Recall stack preload completed (embedding singleton warm).")
    except Exception as e:
        PrintStyle().error(f"Error in _preload_recall_stack: {e}")


# preload transcription model
if __name__ == "__main__":
    PrintStyle().print("Running preload...")
    runtime.initialize()
    asyncio.run(preload())
