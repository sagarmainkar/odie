"""One index for everything (2026-10-14): the file is odie-index.db, and every vector, a note passage's or a picture's,
sits in one vectors table keyed by what it belongs to. An install made before this keeps its vault-index.db contents:
the file is adopted (its write-ahead log folded in first) and its vectors table is carried over as kind "chunk"."""
import shutil
import sqlite3
from array import array
from pathlib import Path

from odie.vault.index import VaultIndex, adopt_old_index, index_path

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"


def _old_style_index(db: Path, vault: Path) -> None:
    """A vault-index.db as the code before today wrote it: the old vectors table, and rows still in the -wal file."""
    c = sqlite3.connect(db)
    c.execute("pragma journal_mode=wal")
    c.executescript("""
        create table notes (path text primary key, mtime real, size integer, sha1 text, title text, aliases text, tags text, links text);
        create table chunks (id integer primary key, path text not null, ord integer, heading text, text text);
        create virtual table chunks_fts using fts5(heading, text, title, tokenize='unicode61 remove_diacritics 2');
        create table vectors (chunk_id integer primary key, vec blob not null);
        create table meta (key text primary key, value text);
    """)
    c.execute("insert into notes values ('Trip.md', 1.0, 10, 'x', 'Trip', '[]', '[]', '[]')")
    c.execute("insert into chunks values (7, 'Trip.md', 0, 'Trip', 'Goa beach')")
    c.execute("insert into chunks_fts(rowid, heading, text, title) values (7, 'Trip', 'Goa beach', 'Trip')")
    c.execute("insert into vectors values (7, ?)", (array("f", [1.0, 0.0]).tobytes(),))
    c.execute("insert into meta values ('model', 'fake:words')")
    c.execute("insert into meta values ('dims', '2')")
    c.commit()
    c.close()  # the rows may still sit in vault-index.db-wal: adopting must not lose them


def test_the_old_file_is_adopted_with_its_vectors(tmp_path):
    data, vault = tmp_path / "data", tmp_path / "vault"
    data.mkdir()
    shutil.copytree(SAMPLE, vault)
    _old_style_index(data / "vault-index.db", vault)
    assert index_path(data) == data / "odie-index.db"
    adopt_old_index(data)
    assert (data / "odie-index.db").is_file() and not (data / "vault-index.db").exists()
    assert not (data / "vault-index.db-wal").exists() and not (data / "vault-index.db-shm").exists()
    ix = VaultIndex(index_path(data), vault)
    st = ix.status()
    assert st["vectors"] == 1 and st["model"] == "fake:words"
    with ix._db() as c:
        rows = c.execute("select kind, ref from vectors").fetchall()
    assert [(r["kind"], r["ref"]) for r in rows] == [("chunk", "7")]


def test_adopting_is_a_no_op_when_there_is_nothing_old_or_the_new_file_exists(tmp_path):
    adopt_old_index(tmp_path)  # nothing there: nothing happens
    assert not (tmp_path / "odie-index.db").exists()
    (tmp_path / "odie-index.db").write_bytes(b"")
    (tmp_path / "vault-index.db").write_bytes(b"old")
    adopt_old_index(tmp_path)  # a new file already: the old one is left alone, never overwritten
    assert (tmp_path / "vault-index.db").read_bytes() == b"old"


def test_a_fresh_index_has_the_one_vectors_table(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(SAMPLE, vault)
    ix = VaultIndex(tmp_path / "odie-index.db", vault)
    with ix._db() as c:
        cols = [r["name"] for r in c.execute("pragma table_info(vectors)")]
    assert cols == ["kind", "ref", "vec"]
