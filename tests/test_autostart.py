import sys

import pytest

from pisumathu.autostart import get_autostart


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_get_autostart_returns_platform_backend():
    backend = get_autostart()
    assert backend.name
    assert callable(backend.is_enabled)


@pytest.mark.skipif(sys.platform == "win32", reason="XDG autostart is Linux-only")
def test_enable_then_disable(isolated_config):
    from pisumathu.autostart.linux import LinuxAutostart, desktop_path

    backend = LinuxAutostart()
    assert backend.is_enabled() is False

    backend.enable()
    assert backend.is_enabled() is True
    assert desktop_path().is_file()

    content = desktop_path().read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "Exec=" in content
    assert "X-GNOME-Autostart-enabled=true" in content

    backend.disable()
    assert backend.is_enabled() is False
    assert not desktop_path().exists()


@pytest.mark.skipif(sys.platform == "win32", reason="XDG autostart is Linux-only")
def test_disable_when_absent_is_noop(isolated_config):
    from pisumathu.autostart.linux import LinuxAutostart

    LinuxAutostart().disable()
    assert LinuxAutostart().is_enabled() is False


@pytest.mark.skipif(sys.platform == "win32", reason="XDG autostart is Linux-only")
def test_enable_is_idempotent(isolated_config):
    from pisumathu.autostart.linux import LinuxAutostart

    backend = LinuxAutostart()
    backend.enable()
    backend.enable()
    assert backend.is_enabled() is True


def test_daemon_never_enables_autostart_by_default():
    """Guard against the old bug: importing the app must not touch autostart."""
    from pisumathu import config

    assert config.Config().autostart is False
