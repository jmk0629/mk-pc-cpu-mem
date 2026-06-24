"""config 로드/오버라이드/권한 게이트 테스트."""
from __future__ import annotations

import os

from pcmon.config import Config


def test_defaults_when_empty():
    cfg = Config.from_dict({})
    assert cfg.thresholds.cpu_percent == 80
    assert cfg.timing.check_interval_seconds == 30
    assert cfg.targets == []


def test_unknown_keys_ignored():
    cfg = Config.from_dict({"thresholds": {"cpu_percent": 70, "bogus": 1}})
    assert cfg.thresholds.cpu_percent == 70


def test_env_token_overrides_file(monkeypatch):
    monkeypatch.setenv("PCMON_TELEGRAM_TOKEN", "ENVTOKEN")
    cfg = Config.from_dict({"telegram": {"token": "filetoken", "chat_ids": [1]}})
    assert cfg.telegram.token == "ENVTOKEN"


def test_chat_id_zero_filtered():
    cfg = Config.from_dict({"telegram": {"chat_ids": [0, 123]}})
    assert cfg.telegram.chat_ids == [123]


def test_permission_gate_falls_back_to_chat_ids():
    cfg = Config.from_dict({"telegram": {"chat_ids": [5], "allowed_user_ids": []}})
    assert cfg.telegram.is_allowed(5) is True
    assert cfg.telegram.is_allowed(6) is False


def test_targets_parsed():
    cfg = Config.from_dict({"targets": [{"name": "a", "type": "docker", "match": "a"}]})
    assert cfg.targets[0].name == "a"
    assert cfg.targets[0].type == "docker"
