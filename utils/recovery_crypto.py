"""Bounded encrypted recovery envelopes using standard Fernet and Argon2id."""

import base64
import os
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

MAGIC = b"PAPER-RECOVERY-ENC-1\n"
MAX_PLAINTEXT = 128 * 1024**2
MAX_ENVELOPE = (MAX_PLAINTEXT + 128) * 4 // 3 + 128


def _fernet(password, salt):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("Use a passphrase of 12 to 1,024 characters.")
    key = Argon2id(
        salt=salt, length=32, iterations=3, lanes=4, memory_cost=2**16
    ).derive(password.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_archive(blob, password):
    if len(blob) > MAX_PLAINTEXT:
        raise ValueError("Encrypted exports are limited to a 128 MiB ZIP payload.")
    salt = os.urandom(16)
    return MAGIC + salt + _fernet(password, salt).encrypt(blob)


def decrypt_archive(envelope, password):
    if len(envelope) > MAX_ENVELOPE or not envelope.startswith(MAGIC):
        raise ValueError("Unsupported or oversized encrypted recovery archive.")
    salt = envelope[len(MAGIC) : len(MAGIC) + 16]
    if len(salt) != 16:
        raise ValueError("Truncated encrypted recovery archive.")
    try:
        blob = _fernet(password, salt).decrypt(envelope[len(MAGIC) + 16 :])
    except InvalidToken:
        raise ValueError("Incorrect passphrase or damaged encrypted archive.") from None
    if len(blob) > MAX_PLAINTEXT:
        raise ValueError("Encrypted archive exceeds the payload limit.")
    return blob
