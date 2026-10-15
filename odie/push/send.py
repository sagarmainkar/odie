"""Send a Web Push notification to every stored subscription; drop the ones that are gone."""
from __future__ import annotations

import json
import logging

from pywebpush import WebPushException, webpush

from odie import config
from odie.push.vapid import load_or_create_vapid
from odie.store.db import Store

log = logging.getLogger("odie.push")


def _private_key_file(vapid: dict) -> str:
    """pywebpush parses `vapid_private_key` as a file path or a DER/raw base64 string, not PEM text.
    Keep the PEM in a 600 file beside vapid.json and hand over the path."""
    pem_path = config.settings.vapid_path.with_name("vapid_private.pem")
    if not pem_path.exists() or pem_path.read_text() != vapid["private_key"]:
        pem_path.parent.mkdir(parents=True, exist_ok=True)
        pem_path.write_text(vapid["private_key"])
        pem_path.chmod(0o600)
    return str(pem_path)


def send_to_all(store: Store, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    vapid = load_or_create_vapid(config.settings.vapid_path)
    key_file = _private_key_file(vapid)
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or "odie"})
    sent = 0
    for sub in store.list_subscriptions():
        info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
        try:
            webpush(subscription_info=info, data=payload, vapid_private_key=key_file,
                    vapid_claims={"sub": vapid["subject"]}, ttl=3600)
            sent += 1
            store.execute("update push_subscriptions set last_ok_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where endpoint=?",
                          (sub["endpoint"],))
        except WebPushException as e:
            response = getattr(e, "response", None)
            code = getattr(response, "status_code", None)
            if code in (404, 410):
                store.delete_subscription(sub["endpoint"])
            else:
                log.warning("push failed %s: %s", sub["endpoint"][:40], e)
    return sent
