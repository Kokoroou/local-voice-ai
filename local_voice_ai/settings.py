"""Settings UI backend: validate, persist, and hot-apply STT/LLM/TTS choices.

Bridges the ``/api/config`` HTTP layer (``api.py``) and process lifecycle
(``Supervisor.replace_child``). A change is validated by attempting to build a
``Config`` from it (reusing ``Config.from_env``'s own parsing — the same
thing that would otherwise crash the *next* boot on a bad value), persisted
to disk, then diffed against the currently-running ``ChildSpec``s so only the
children actually affected are restarted.

Deliberately out of scope: anything that would need the Supervisor to add or
drop a managed child entirely (e.g. pointing a backend at a remote/cloud API)
rather than swap one already-managed child for another. Also out of scope:
ports, LIVEKIT_*, DEVICE, LLAMA_N_GPU_LAYERS, WEB_HOST — platform/network
config that stays docker-compose/.env.local-only, since getting it wrong here
could strand the user's own connection to the page serving this UI.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import settings_store
from .config import Config
from .profiles import ProfileCatalog, detect_hardware, load_catalog
from .supervisor import ChildSpec, Supervisor

logger = logging.getLogger("settings")

# Env vars the Settings UI may change. Everything else is rejected outright —
# not an oversight to fill in later, a deliberate boundary (see module docstring).
ALLOWED_KEYS = frozenset(
    {
        "STT_PROVIDER",
        "STT_LANGUAGE",
        "TTS_PROVIDER",
        "TTS_VOICE",
        "LLAMA_HF_REPO",
        "LLAMA_MODEL",
        "LLAMA_MODEL_ALIAS",
        "LLAMA_CTX_SIZE",
        "WAKE_WORD",
        "WAKE_WORD_THRESHOLD",
        "TURN_DETECTION",
    }
)

# A "role" is a slot the Settings UI can retarget. Most roles keep one fixed
# child name regardless of provider; STT is the exception — "nemotron-cpp"
# and "nemotron" both build a child named "nemotron", but "whisper" builds a
# differently-named one, so the role can point at either identity.
_ROLE_CHILD_NAMES: Mapping[str, tuple[str, ...]] = {
    "llm": ("llama",),
    "stt": ("nemotron", "whisper"),
    "tts": ("kokoro",),
    "agent": ("agent",),
}


class SettingsError(ValueError):
    """A proposed settings change is invalid; nothing was persisted or restarted."""


@dataclass
class ApplyResult:
    restarted: list[str] = field(default_factory=list)


def _role_spec(specs_by_name: Mapping[str, ChildSpec], role: str) -> ChildSpec:
    for name in _ROLE_CHILD_NAMES[role]:
        spec = specs_by_name.get(name)
        if spec is not None:
            return spec
    raise AssertionError(
        f"no child for role {role!r} — the Settings UI assumes STT/LLM/TTS/agent "
        "stay locally managed (manage_* must be True)"
    )


class SettingsController:
    def __init__(
        self,
        *,
        supervisor: Supervisor,
        settings_path: Path,
        specs_builder: Callable[[Config], list[ChildSpec]],
        catalog: ProfileCatalog | None = None,
    ) -> None:
        self._supervisor = supervisor
        self._settings_path = settings_path
        self._specs_builder = specs_builder
        self._catalog = catalog or load_catalog()
        # Keep a strong reference to in-flight restarts — asyncio only holds
        # a weak one, so an unreferenced task can be garbage-collected mid-run.
        self._background_tasks: set[asyncio.Task] = set()

    def _expand_profile(self, changes: Mapping[str, str]) -> dict[str, str]:
        """A ``{"profile": "lean"}`` shorthand expands to that profile's env
        dict; any other keys in ``changes`` still override it afterwards, so
        Advanced-mode fields can layer on top of a chosen profile."""
        expanded = dict(changes)
        profile_key = expanded.pop("profile", None)
        if profile_key is None:
            return expanded
        try:
            profile = self._catalog.models[profile_key]
        except KeyError as exc:
            choices = ", ".join(sorted(self._catalog.models))
            raise SettingsError(f"unknown profile {profile_key!r}; choose one of: {choices}") from exc
        merged = dict(profile.environment)
        merged.update(expanded)
        return merged

    def snapshot(self) -> dict[str, object]:
        """Current effective settings + the profile catalog, for GET /api/config."""
        hardware = detect_hardware()
        cfg = Config.from_env()
        profiles = [
            {
                "key": model.key,
                "label": model.label,
                "description": model.description,
                "llm": model.llm,
                "stt": model.stt,
                "tts": model.tts,
                "target_memory_gib": model.target_memory_gib,
                "download_gib": model.download_gib,
                "supported": model.supports(hardware.platform_key),
            }
            for model in self._catalog.ordered_models()
        ]
        return {
            "current": {
                "stt_provider": cfg.stt_provider,
                "stt_language": cfg.stt_language,
                "tts_provider": cfg.tts_provider,
                "tts_voice": cfg.tts_voice,
                "llama_hf_repo": cfg.llama_hf_repo,
                "llama_model": cfg.llama_model,
                "llama_ctx_size": cfg.llama_ctx_size,
                "wake_word": cfg.wake_word,
                "wake_word_threshold": cfg.wake_word_threshold,
                "turn_detection": cfg.turn_detection,
            },
            "platform_key": hardware.platform_key,
            "profiles": profiles,
        }

    def apply(self, changes: Mapping[str, object]) -> ApplyResult:
        """Validate + persist ``changes``, then kick off restarts in the background.

        Restarts are *not* awaited here — a first-run model download can take
        minutes, far longer than an HTTP request should block for. The caller
        (the ``/api/config`` route) gets back the list of children now
        restarting; the frontend watches the existing ``/api/status`` poll,
        exactly like first boot, to see them come back ready.
        """
        changes = {str(k): str(v) for k, v in changes.items()}
        # Whitelist-check only the caller-supplied keys, not what a chosen
        # profile itself contributes below — profiles.json is a curated,
        # already-vetted source (it may set e.g. LLAMA_PARALLEL/STT_MODEL,
        # which aren't exposed as standalone Advanced-mode fields), whereas
        # free-form Advanced-mode input is what ALLOWED_KEYS is guarding.
        unknown = (set(changes) - {"profile"}) - ALLOWED_KEYS
        if unknown:
            raise SettingsError(
                f"not settable via the Settings UI: {', '.join(sorted(unknown))}"
            )
        expanded = self._expand_profile(changes)

        old_cfg = Config.from_env()
        old_specs = {spec.name: spec for spec in self._specs_builder(old_cfg)}

        trial_env = {**os.environ, **expanded}
        try:
            new_cfg = Config.from_env(trial_env)
        except (ValueError, TypeError) as exc:
            raise SettingsError(f"invalid settings: {exc}") from exc
        new_specs = {spec.name: spec for spec in self._specs_builder(new_cfg)}

        # old_name -> new_spec, for every role whose (name, argv, env) changed.
        restarts: dict[str, ChildSpec] = {}
        for role in _ROLE_CHILD_NAMES:
            old_spec = _role_spec(old_specs, role)
            new_spec = _role_spec(new_specs, role)
            if (old_spec.name, old_spec.argv, old_spec.env) != (
                new_spec.name,
                new_spec.argv,
                new_spec.env,
            ):
                restarts[old_spec.name] = new_spec

        if not expanded:
            return ApplyResult(restarted=[])

        persisted = settings_store.load(self._settings_path)
        persisted.update(expanded)
        settings_store.save(self._settings_path, persisted)
        os.environ.update(expanded)

        for old_name, new_spec in restarts.items():
            task = asyncio.create_task(self._restart(old_name, new_spec))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return ApplyResult(restarted=[spec.name for spec in restarts.values()])

    async def _restart(self, old_name: str, spec: ChildSpec) -> None:
        try:
            await self._supervisor.replace_child(old_name, spec)
            logger.info("[%s] settings applied; now running %s", old_name, spec.name)
        except Exception:
            logger.exception("[%s] failed to apply new settings (target: %s)", old_name, spec.name)
