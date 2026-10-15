"""VAPID key pair for Web Push, generated once and kept chmod 600 in the data dir."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def contact_subject() -> str:
    """Who push services can contact about this sender: ODIE_CONTACT_EMAIL (environment or ~/.odie/.env),
    else Odie's own address. Only used when the keys are first created."""
    from odie import config
    from odie.secrets import load_secret
    email = load_secret("ODIE_CONTACT_EMAIL")
    return f"mailto:{email}" if email else config.settings.public_url


def load_or_create_vapid(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    data = {"private_key": pem, "public_key": base64.urlsafe_b64encode(pub).decode().rstrip("="),
            "subject": contact_subject()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return data
