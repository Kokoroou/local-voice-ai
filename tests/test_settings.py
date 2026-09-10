"""Tests for local_voice_ai.settings.SettingsController and settings_store.

A fake Supervisor stands in for the real one: SettingsController only ever
calls ``replace_child``, so recording those calls is enough to verify the
diff-and-restart logic without spawning real child processes.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from local_voice_ai import settings_store
from local_voice_ai.config import Config
from local_voice_ai.settings import SettingsController, SettingsError
from local_voice_ai.supervisor import ChildSpec


class TestSettingsStore:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert settings_store.load(tmp_path / "settings.json") == {}

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "settings.json"
        settings_store.save(path, {"STT_PROVIDER": "whisper"})
        assert settings_store.load(path) == {"STT_PROVIDER": "whisper"}

    def test_corrupt_file_is_treated_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("not json")
        assert settings_store.load(path) == {}

    def test_save_overwrites_atomically_and_leaves_no_temp_file(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        settings_store.save(path, {"A": "1"})
        settings_store.save(path, {"A": "2"})
        assert settings_store.load(path) == {"A": "2"}
        assert not path.with_suffix(path.suffix + ".tmp").exists()


def _fake_specs_builder(cfg: Config) -> list[ChildSpec]:
    """Stand-in for __main__._build_specs: only the fields the Settings UI
    can touch feed into each child's (name, argv, env) — enough to exercise
    the diff logic without a real Config -> argv translation."""
    return [
        ChildSpec(
            name="llama",
            argv=["llama-server", "--hf-repo", cfg.llama_hf_repo, "--ctx-size", str(cfg.llama_ctx_size)],
        ),
        ChildSpec(
            name=("whisper" if cfg.stt_provider == "whisper" else "nemotron"),
            argv=["stt", cfg.stt_provider],
            env={"STT_LANGUAGE": cfg.stt_language},
        ),
        ChildSpec(name="kokoro", argv=["tts", cfg.tts_voice]),
        ChildSpec(name="agent", argv=["agent"], env=cfg.agent_env()),
    ]


class FakeSupervisor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ChildSpec]] = []

    async def replace_child(self, old_name: str, spec: ChildSpec) -> None:
        self.calls.append((old_name, spec))


@pytest.fixture
def controller(tmp_path: Path) -> tuple[SettingsController, FakeSupervisor]:
    sup = FakeSupervisor()
    ctrl = SettingsController(
        supervisor=sup,
        settings_path=tmp_path / "settings.json",
        specs_builder=_fake_specs_builder,
    )
    return ctrl, sup


class TestApplyValidation:
    def test_rejects_unknown_keys(
        self, controller: tuple[SettingsController, FakeSupervisor]
    ) -> None:
        ctrl, sup = controller
        with pytest.raises(SettingsError):
            ctrl.apply({"WEB_PORT": "9999"})
        assert sup.calls == []

    def test_rejects_bad_values_without_persisting_or_mutating_env(
        self, controller: tuple[SettingsController, FakeSupervisor], tmp_path: Path
    ) -> None:
        ctrl, sup = controller
        with pytest.raises(SettingsError):
            ctrl.apply({"LLAMA_CTX_SIZE": "not-a-number"})
        assert sup.calls == []
        assert not (tmp_path / "settings.json").exists()
        assert "LLAMA_CTX_SIZE" not in os.environ

    def test_unknown_profile_is_rejected(
        self, controller: tuple[SettingsController, FakeSupervisor]
    ) -> None:
        ctrl, sup = controller
        with pytest.raises(SettingsError):
            ctrl.apply({"profile": "does-not-exist"})
        assert sup.calls == []


class TestApplyRestartsOnlyAffectedChildren:
    @pytest.mark.asyncio
    async def test_ctx_size_change_restarts_only_llama(
        self, controller: tuple[SettingsController, FakeSupervisor], tmp_path: Path
    ) -> None:
        ctrl, sup = controller
        result = ctrl.apply({"LLAMA_CTX_SIZE": "8192"})
        assert result.restarted == ["llama"]
        await asyncio.sleep(0)  # let the scheduled restart task run
        assert [name for name, _ in sup.calls] == ["llama"]
        assert settings_store.load(tmp_path / "settings.json") == {"LLAMA_CTX_SIZE": "8192"}

    @pytest.mark.asyncio
    async def test_stt_language_change_restarts_stt_and_agent_not_llama_or_tts(
        self, controller: tuple[SettingsController, FakeSupervisor]
    ) -> None:
        ctrl, sup = controller
        result = ctrl.apply({"STT_LANGUAGE": "fr-FR"})
        assert set(result.restarted) == {"nemotron", "agent"}
        await asyncio.sleep(0)
        assert {name for name, _ in sup.calls} == {"nemotron", "agent"}

    @pytest.mark.asyncio
    async def test_stt_provider_switch_renames_the_child(
        self, controller: tuple[SettingsController, FakeSupervisor]
    ) -> None:
        ctrl, sup = controller
        result = ctrl.apply({"STT_PROVIDER": "whisper"})
        assert "whisper" in result.restarted
        await asyncio.sleep(0)
        old_names = {name for name, _ in sup.calls}
        new_names = {spec.name for _, spec in sup.calls}
        assert "nemotron" in old_names  # replace_child looked up the *old* identity
        assert "whisper" in new_names

    @pytest.mark.asyncio
    async def test_no_changes_restarts_nothing(
        self, controller: tuple[SettingsController, FakeSupervisor]
    ) -> None:
        ctrl, sup = controller
        result = ctrl.apply({})
        assert result.restarted == []
        await asyncio.sleep(0)
        assert sup.calls == []

    @pytest.mark.asyncio
    async def test_profile_shorthand_expands_and_restarts_llama(
        self, controller: tuple[SettingsController, FakeSupervisor]
    ) -> None:
        ctrl, _sup = controller
        result = ctrl.apply({"profile": "lean"})
        await asyncio.sleep(0)
        assert "llama" in result.restarted

    @pytest.mark.asyncio
    async def test_advanced_field_overrides_the_chosen_profile(
        self, controller: tuple[SettingsController, FakeSupervisor], tmp_path: Path
    ) -> None:
        ctrl, _sup = controller
        ctrl.apply({"profile": "lean", "STT_LANGUAGE": "fr-FR"})
        await asyncio.sleep(0)
        assert settings_store.load(tmp_path / "settings.json")["STT_LANGUAGE"] == "fr-FR"


class TestSnapshot:
    def test_snapshot_shape(
        self, controller: tuple[SettingsController, FakeSupervisor]
    ) -> None:
        ctrl, _ = controller
        snap = ctrl.snapshot()
        assert set(snap) == {"current", "platform_key", "profiles"}
        assert any(p["key"] == "compact" for p in snap["profiles"])
        assert {"stt_provider", "llama_hf_repo", "tts_voice"} <= set(snap["current"])
