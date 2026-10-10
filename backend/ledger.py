"""Private hash-chain ledger for tamper-evident registration and incident records.

This is a simple append-only chain stored in the app database, not a public blockchain: anyone with
database write access could rewrite it wholesale. It does make silent edits to individual records
detectable, and it never stores personal data -- only salted hashes. Anchor `head()` on a public chain
if you need stronger guarantees.
"""
import hashlib, threading
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from . import models as m
from .database import SessionLocal

GENESIS = '0' * 64
_lock = threading.Lock()


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def block_hash(idx, ts, block_type, ref, payload_hash, prev_hash):
    return sha256('|'.join(str(x) for x in (idx, ts, block_type, ref, payload_hash, prev_hash)))


def append(block_type: str, ref: str, payload_hash: str) -> m.LedgerBlock:
    """Append in its own short transaction so concurrent requests can't race on the chain index."""
    with _lock, SessionLocal() as s:
        if s.bind.dialect.name == 'postgresql':  # the thread lock only covers this process; this covers all of them
            s.execute(text('SELECT pg_advisory_xact_lock(7001)'))
        last = s.query(m.LedgerBlock).order_by(m.LedgerBlock.idx.desc()).first()
        idx = last.idx + 1 if last else 0
        prev = last.hash if last else GENESIS
        ts = datetime.now(timezone.utc).isoformat()
        b = m.LedgerBlock(idx=idx, ts=ts, block_type=block_type, ref=ref, payload_hash=payload_hash,
                          prev_hash=prev, hash=block_hash(idx, ts, block_type, ref, payload_hash, prev))
        s.add(b)
        s.commit()
        s.refresh(b)
        s.expunge(b)
        return b


def ensure_genesis():
    with SessionLocal() as s:
        if s.query(m.LedgerBlock).count():
            return
    append('GENESIS', '-', sha256('team-limitless-ledger'))


def verify(db: Session):
    prev, n = GENESIS, 0
    for b in db.query(m.LedgerBlock).order_by(m.LedgerBlock.idx):
        if b.idx != n or b.prev_hash != prev or b.hash != block_hash(b.idx, b.ts, b.block_type, b.ref, b.payload_hash, b.prev_hash):
            return {'valid': False, 'broken_at': b.idx, 'blocks': n}
        prev, n = b.hash, n + 1
    return {'valid': True, 'blocks': n, 'head': prev}


def block_out(b: m.LedgerBlock):
    return dict(index=b.idx, timestamp=b.ts, type=b.block_type, ref=b.ref, payload_hash=b.payload_hash,
                prev_hash=b.prev_hash, hash=b.hash)
