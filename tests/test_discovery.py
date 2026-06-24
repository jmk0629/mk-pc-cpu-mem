"""자동 발견 필터링 + DiscoveryConfig 테스트 (순수 로직)."""
from __future__ import annotations

from pcmon.config import Config
from pcmon.discovery import _filter, discover


def test_filter_excludes_substring_and_systemd_family():
    names = [
        "systemd-journald.service", "systemd-logind.service",
        "cron.service", "ssh.service", "docker.service",
        "caddy.service", "meditv-report.service",
    ]
    exclude = ["cron", "ssh", "dbus", "systemd", "docker", "snapd"]
    kept = _filter(names, exclude)
    assert "caddy.service" in kept
    assert "meditv-report.service" in kept
    # 제외 대상은 모두 빠짐
    assert all(x not in kept for x in [
        "systemd-journald.service", "systemd-logind.service",
        "cron.service", "ssh.service", "docker.service",
    ])


def test_filter_ignores_service_suffix_in_match():
    # exclude 에 'portainer' 만 있어도 컨테이너명 'portainer' 제외
    assert _filter(["portainer", "open-design"], ["portainer"]) == ["open-design"]


def test_filter_case_insensitive():
    assert _filter(["NetworkManager.service"], ["networkmanager"]) == []


def test_discover_disabled_returns_empty():
    cfg = Config.from_dict({"discovery": {"enabled": False}})
    assert discover(cfg) == []


def test_discovery_config_defaults():
    cfg = Config.from_dict({})
    assert cfg.discovery.enabled is False
    assert cfg.discovery.docker is True
    assert cfg.discovery.refresh_minutes == 5


def test_discovery_config_parsed():
    cfg = Config.from_dict({"discovery": {"enabled": True, "systemd": False, "refresh_minutes": 10}})
    assert cfg.discovery.enabled is True
    assert cfg.discovery.systemd is False
    assert cfg.discovery.refresh_minutes == 10
