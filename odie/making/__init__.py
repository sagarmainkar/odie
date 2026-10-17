"""Things Odie makes in the background, after the chat turn that asked for them has ended: explainer videos and
podcasts today, decks next. Each is one kind of job with two steps: writing (a focused model turn that sees only the
job's brief and one submit tool, odie.making.writer) and making (no AI: render, speak or build the file). The queue
(odie.making.jobs) runs one job at a time and posts the result into the chat it was asked in, with a phone push. The
chat tools that start jobs share their argument reading, checks and reply (odie.making.chat)."""
