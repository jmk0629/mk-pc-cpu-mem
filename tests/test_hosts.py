"""멀티호스트 — config 파싱 + Monitor 타겟 구성 테스트."""
from __future__ import annotations

from pcmon import discovery
from pcmon.config import Config, Target
from pcmon.monitor import Monitor, _label, _tid


def test_hosts_parsed():
    cfg = Config.from_dict({
        "hosts": [
            {"name": "Mac", "host": "", "system": True},
            {"name": "미니PC", "host": "keymedi1", "discovery": True},
        ],
    })
    assert len(cfg.hosts) == 2
    assert cfg.hosts[0].name == "Mac" and cfg.hosts[0].system is True
    assert cfg.hosts[1].host == "keymedi1" and cfg.hosts[1].discovery is True


def test_legacy_fallback_builds_single_host():
    cfg = Config.from_dict({
        "remote": {"host": "keymedi1"},
        "discovery": {"enabled": True},
        "targets": [{"name": "x", "type": "docker", "match": "x"}],
    })
    assert len(cfg.hosts) == 1
    h = cfg.hosts[0]
    assert h.host == "keymedi1" and h.discovery is True
    # 레거시 타겟에 host 가 채워짐
    assert h.targets[0].host == "keymedi1"


def test_explicit_target_host_in_hosts():
    cfg = Config.from_dict({
        "hosts": [{"name": "미니PC", "host": "keymedi1",
                   "targets": [{"name": "open-design", "type": "docker", "match": "open-design"}]}],
    })
    t = cfg.hosts[0].targets[0]
    assert t.host == "keymedi1"


def test_monitor_builds_multi_host_targets(monkeypatch):
    # discovery 는 SSH 대신 고정값으로 모킹
    def fake_discover_for(cfg, host):
        if host == "keymedi1":
            return [Target("open-design", "docker", "open-design", host="keymedi1")]
        return []

    monkeypatch.setattr(discovery, "discover_for", fake_discover_for)
    cfg = Config.from_dict({
        "telegram": {},  # 토큰 없음 → 알림 no-op
        "hosts": [
            {"name": "Mac", "host": "", "system": True},
            {"name": "미니PC", "host": "keymedi1", "discovery": True},
        ],
    })
    mon = Monitor(cfg)
    # Mac system 타겟 + 미니PC 발견 docker 타겟
    labels = sorted(_label(t) for t in mon.targets.values())
    assert "Mac" in labels                       # 로컬 system
    assert "open-design @keymedi1" in labels      # 원격 발견
    # tid 가 호스트로 구분됨
    tids = set(mon.targets)
    assert "|Mac" in tids
    assert "keymedi1|open-design" in tids


def test_tid_and_label():
    local = Target("Mac", "system", "", host="")
    remote = Target("open-design", "docker", "open-design", host="keymedi1")
    assert _tid(local) == "|Mac"
    assert _tid(remote) == "keymedi1|open-design"
    assert _label(local) == "Mac"
    assert _label(remote) == "open-design @keymedi1"
