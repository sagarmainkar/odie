"""The watch's threads of old (22 Oct to 19 Nov 2026): the orders, bills, replies owed and deadlines it followed, kept
as rows in the tasks table with source_kind "watch". Since phase 3 of the proactive design every one of them is a loop
(odie.loops: the upgrade, odie.loops.migrate, carried them over), and the watch's `track_thread` writes findings that
stage 2 places in the ledger. The old rows stay where they were (a rollback finds them); an open one is the loop's to
show, never a card of its own, and its reminder (a bill's date) still rings."""
from __future__ import annotations

SOURCE_KIND = "watch"
