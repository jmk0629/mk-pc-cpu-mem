"""watchdog heartbeat 만료 판정 테스트."""
from __future__ import annotations

import time

from pcmon.watchdog import heartbeat_age_minutes


def test_missing_file_returns_none(tmp_path):
    assert heartbeat_age_minutes(str(tmp_path / "nope")) is None


def test_fresh_heartbeat(tmp_path):
    p = tmp_path / "hb"
    p.write_text(str(time.time()))
    age = heartbeat_age_minutes(str(p))
    assert age is not None and age < 0.1


def test_stale_heartbeat(tmp_path):
    p = tmp_path / "hb"
    p.write_text(str(time.time() - 600))  # 10분 전
    age = heartbeat_age_minutes(str(p))
    assert age is not None and age >= 9.5
