from odie.push import send as sendmod
from odie.push.vapid import load_or_create_vapid
from odie.store.db import Store


def test_vapid_persisted(tmp_path):
    a = load_or_create_vapid(tmp_path / "v.json")
    b = load_or_create_vapid(tmp_path / "v.json")
    assert a == b and a["public_key"].startswith("B") and len(a["public_key"]) == 87


def test_send_drops_gone(tmp_path, monkeypatch):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.add_subscription("https://ok/1", "k", "a")
    s.add_subscription("https://gone/2", "k", "a")

    class Resp:
        def __init__(self, code):
            self.status_code = code

    def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, ttl):
        import os
        assert os.path.isfile(vapid_private_key), "pywebpush needs a PEM file path (or DER string), never PEM text"
        if "gone" in subscription_info["endpoint"]:
            raise sendmod.WebPushException("gone", response=Resp(410))
        return Resp(201)

    monkeypatch.setattr(sendmod, "webpush", fake_webpush)
    real = load_or_create_vapid(tmp_path / "v.json")
    monkeypatch.setattr(sendmod, "load_or_create_vapid", lambda p: real)
    monkeypatch.setattr(sendmod.config.settings.__class__, "vapid_path", property(lambda self: tmp_path / "v.json"))
    assert sendmod.send_to_all(s, "Odie", "hi") == 1
    assert [r["endpoint"] for r in s.list_subscriptions()] == ["https://ok/1"]
