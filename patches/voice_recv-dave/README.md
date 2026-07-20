# voice_recv DAVE patch

These two files overlay the installed `discord-ext-voice-recv` package
(the `dave-decrypt` fork pinned in `Herupa/requirements.txt`) and are
required for `$mock` voice receive to work reliably.

What they fix (2026-07-17): the fork decrypts DAVE (Discord's voice E2EE)
frames, but when a frame *can't* be decrypted (the SSRC-to-user mapping
hasn't arrived yet, or the MLS key ratchet is mid-rotation after someone
joins/leaves the channel) it handed the still-encrypted bytes to the opus
decoder. That raised `OpusError: corrupted stream`, which killed the
packet-router thread for the rest of the session, so the bot went deaf and
mocks were refunded as "target never spoke".

Patched behavior:

- `opus.py` - `_dave_decrypt` reports whether the frame is usable;
  undecryptable or undecodable frames are dropped (with rate-limited log
  lines) instead of crashing the pipeline. Silence keepalives, which are
  legitimately plaintext under DAVE, still pass through.
- `router.py` - the packet router survives any per-packet error instead of
  treating the first one as fatal.

Apply by copying both files over the installed package (done automatically
by `scripts/setup.sh`):

```sh
SITE=$(python3 -c "import discord.ext.voice_recv, os; print(os.path.dirname(discord.ext.voice_recv.__file__))")
cp patches/voice_recv-dave/opus.py patches/voice_recv-dave/router.py "$SITE/"
```

Reapply after ANY reinstall or upgrade of `discord-ext-voice-recv`. The
patch matches version `0.5.3a181` of the fork; if the pin ever moves,
re-diff these files against the new version first. Ideally this patch gets
upstreamed or the fork gets forked properly someday.
