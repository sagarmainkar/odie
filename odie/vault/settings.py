"""Where the vault is, which folders to leave out, and which embedding model reads it by meaning (none: keyword search
only). Kept in the store's settings as "vault"; the index (odie-index.db, notes and photos alike) lives in the data
folder."""
from __future__ import annotations

from pathlib import Path

from odie import config
from odie.vault.embed import EmbedError, Embedder, make_embedder
from odie.vault.index import VaultIndex, adopt_old_index, index_path

KEY = "vault"
_KEEP = object()
_indexes: dict[tuple, VaultIndex] = {}


def get(store) -> dict:
    v = store.get_setting(KEY) or {}
    return {"dir": v.get("dir"), "ignore": list(v.get("ignore") or []), "embeddings": v.get("embeddings")}


def put(store, dir=_KEEP, ignore=_KEEP, embeddings=_KEEP) -> dict:
    """Save what's given; leave a field out to keep it. dir None or "" turns the index off; otherwise a full path to a
    folder that exists. embeddings None switches meaning search off."""
    v = get(store)
    if dir is not _KEEP:
        if not dir:
            v["dir"] = None
        else:
            p = Path(dir).expanduser()
            if not p.is_absolute():
                raise ValueError(f"The notes folder needs a full path (like /Users/you/Notes), not {dir!r}.")
            if not p.is_dir():
                raise ValueError(f"No folder at {p}.")
            v["dir"] = str(p.resolve())
    if ignore is not _KEEP:
        v["ignore"] = [i.strip().strip("/") for i in ignore or [] if i and i.strip().strip("/")]
    if embeddings is not _KEEP:
        v["embeddings"] = ({"provider": embeddings["provider"], "model": embeddings["model"]} if embeddings else None)
    store.set_setting(KEY, v)
    return v


def configured(store) -> bool:
    d = get(store)["dir"]
    return bool(d) and Path(d).is_dir()


def index_for(store) -> VaultIndex | None:
    """The index (one per folder and ignore list, so its vector cache is kept), or None when there's nothing to index:
      a notes folder set                         -> the index over that folder (and the photos, when they're on)
      no folder, photos on                       -> the index with no notes folder: photos alone
      neither, but odie-index.db already there   -> the index as it is (so switching photos off can forget them)
      neither, no file                           -> None"""
    from odie.photos import settings as photos
    v = get(store)
    data_dir = config.settings.data_dir
    has_notes = configured(store)
    if not has_notes and not photos.is_on(store) and not index_path(data_dir).exists():
        return None
    folder = v["dir"] if has_notes else None
    key = (str(data_dir), folder, tuple(v["ignore"]))
    if key not in _indexes:
        _indexes.clear()  # one at a time: an old one's vector cache is let go
        adopt_old_index(data_dir)
        _indexes[key] = VaultIndex(index_path(data_dir), Path(folder) if folder else None, v["ignore"])
    return _indexes[key]


def embedder_for(store) -> Embedder | None:
    return embedder_and_reason(store)[0]


def embedder_and_reason(store) -> tuple[Embedder | None, str]:
    """The embedder meaning search uses, or None and why (not set: ""; set but unusable: the reason)."""
    e = get(store)["embeddings"]
    if not e:
        return None, ""
    try:
        return make_embedder(e["provider"], e["model"], store), ""
    except EmbedError as err:
        return None, str(err)
