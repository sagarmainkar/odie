import importlib
import subprocess

import pytest

from odie import region


def test_timezone_from_the_localtime_link(tmp_path):
    for target, zone in (("/var/db/timezone/zoneinfo/Asia/Kolkata", "Asia/Kolkata"),
                         ("/usr/share/zoneinfo/Europe/Berlin", "Europe/Berlin"),
                         ("../usr/share/zoneinfo/America/New_York", "America/New_York")):
        link = tmp_path / zone.replace("/", "_")
        link.symlink_to(target)
        assert region.system_timezone(link, tmp_path / "none") == zone


def test_timezone_from_debian_file(tmp_path):
    (tmp_path / "timezone").write_text("Europe/Paris\n")
    assert region.system_timezone(tmp_path / "no-link", tmp_path / "timezone") == "Europe/Paris"


def test_timezone_falls_back_to_utc(tmp_path):
    link = tmp_path / "localtime"
    link.symlink_to("/usr/share/zoneinfo/Mars/Olympus_Mons")
    (tmp_path / "timezone").write_text("not a zone")
    assert region.system_timezone(link, tmp_path / "timezone") == "UTC"
    plain = tmp_path / "plainfile"
    plain.write_text("x")  # a copied file, not a link
    assert region.system_timezone(plain, tmp_path / "none") == "UTC"


@pytest.mark.parametrize("raw, want", [
    ("en_IN", "en-IN"), ("en_US.UTF-8", "en-US"), ("de_DE@euro", "de-DE"), ("zh_Hans_CN", "zh-Hans-CN"),
    ("en-GB", "en-GB"), ("fr", "fr"), ("C", None), ("POSIX", None), ("C.UTF-8", None), ("", None), (None, None),
    ("12_34", None),
])
def test_locale_strings_normalise(raw, want):
    assert region.normalize_locale(raw) == want


def test_macos_reads_the_system_region():
    def run(cmd, **kw):
        assert cmd == ["defaults", "read", "-g", "AppleLocale"]
        return subprocess.CompletedProcess(cmd, 0, stdout="en_IN\n", stderr="")
    assert region.system_locale("darwin", {}, run) == "en-IN"


def test_macos_without_defaults_uses_lang():
    def broken(cmd, **kw):
        raise OSError("no defaults")
    assert region.system_locale("darwin", {"LANG": "en_GB.UTF-8"}, broken) == "en-GB"


def test_linux_reads_lc_all_then_lang():
    assert region.system_locale("linux", {"LC_ALL": "de_DE.UTF-8", "LANG": "en_US.UTF-8"}) == "de-DE"
    assert region.system_locale("linux", {"LANG": "C.UTF-8"}) == "en-US"


def test_country_and_currency():
    assert region.country_of("en-IN") == "IN" and region.country_of("zh-Hans-CN") == "CN" and region.country_of("fr") == ""
    assert region.currency_for("IN") == "INR" and region.currency_for("DE") == "EUR" and region.currency_for("") == "USD"
    assert region.currency_symbol("INR") == "₹" and region.currency_symbol("XYZ") == "XYZ"


def test_config_overrides_and_bad_values(isolated_settings, monkeypatch):
    import odie.config as c
    monkeypatch.setenv("ODIE_TIMEZONE", "Europe/Berlin")
    monkeypatch.setenv("ODIE_LOCALE", "de_DE.UTF-8")
    s = importlib.reload(c).settings
    assert (s.timezone, s.locale, s.country, s.currency) == ("Europe/Berlin", "de-DE", "DE", "EUR")
    monkeypatch.setenv("ODIE_TIMEZONE", "Mars/Base")
    monkeypatch.setenv("ODIE_CURRENCY", "gbp")
    s = importlib.reload(c).settings
    assert s.timezone == region.system_timezone() and s.currency == "GBP"
