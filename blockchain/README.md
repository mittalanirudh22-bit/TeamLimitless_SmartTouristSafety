# Blockchain integrity layer
Use blockchain for tamper-evident incident integrity, not for storing PII or raw GPS.

Recommended flow:
incident JSON -> canonical serialization -> SHA-256 hash -> on-chain hash/reference.
