"""
Axon — Secure Vault
AES-256-GCM encryption at rest + TOTP 2FA.

Security model:
  - Master password is NEVER stored. Only its PBKDF2 hash is stored for verification.
  - Each secret is encrypted with AES-256-GCM using a key derived from the master password.
  - The vault is locked at startup. A valid master password + TOTP code is required to unlock.
  - The derived encryption key lives only in memory while the vault is unlocked.
  - Locking clears the in-memory key.
"""

import os
import base64
import hashlib
import hmac
import struct
import time
import io
from typing import Optional
from pathlib import Path

import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# ─── In-memory vault session ──────────────────────────────────────────────────

class VaultSession:
    """Singleton holding the in-memory unlock state."""
    _key: Optional[bytes] = None          # AES-256 key (32 bytes)
    _unlocked_at: Optional[float] = None  # epoch seconds
    SESSION_TTL = 86400                   # auto-lock after 24 hours

    @classmethod
    def unlock(cls, key: bytes):
        cls._key = key
        cls._unlocked_at = time.time()

    @classmethod
    def lock(cls):
        cls._key = None
        cls._unlocked_at = None

    @classmethod
    def is_unlocked(cls) -> bool:
        if cls._key is None:
            return False
        if time.time() - cls._unlocked_at > cls.SESSION_TTL:
            cls.lock()
            return False
        return True

    @classmethod
    def get_key(cls) -> Optional[bytes]:
        if not cls.is_unlocked():
            return None
        cls._unlocked_at = time.time()  # refresh TTL on activity
        return cls._key


# ─── Key derivation ───────────────────────────────────────────────────────────

def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from a master password using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,   # OWASP 2023 recommendation
    )
    return kdf.derive(password.encode("utf-8"))


def hash_password_for_storage(password: str, salt: bytes) -> str:
    """One-way hash for verifying the master password without storing it."""
    key = derive_key(password, salt)
    # Double-hash: key material shouldn't be directly used for verification
    digest = hashlib.sha256(key + b"devbrain_vault_verify").hexdigest()
    return digest


# ─── Encryption / Decryption ─────────────────────────────────────────────────

def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt a string with AES-256-GCM. Returns base64-encoded nonce+ciphertext."""
    nonce = os.urandom(12)   # GCM nonce: 96 bits
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    combined = nonce + ciphertext
    return base64.b64encode(combined).decode("ascii")


def decrypt(encoded: str, key: bytes) -> str:
    """Decrypt AES-256-GCM encoded string. Raises on tamper/wrong key."""
    combined = base64.b64decode(encoded.encode("ascii"))
    nonce = combined[:12]
    ciphertext = combined[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# ─── TOTP helpers ─────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """Generate a new Base32 TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, account_name: str = "Axon Secure Vault") -> str:
    """Return an otpauth:// URI for QR code generation."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_name,
        issuer_name="Axon"
    )


def generate_qr_data_uri(secret: str) -> str:
    """Generate a base64 PNG data URI of the TOTP QR code."""
    try:
        import qrcode
        uri = get_totp_uri(secret)
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=6,
            border=2,
        )
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        return ""


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. Allows ±1 time step for clock drift."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


# ─── Vault DB operations ──────────────────────────────────────────────────────

async def vault_is_setup(db) -> bool:
    """Return True if the vault master password has been configured."""
    cur = await db.execute("SELECT value FROM settings WHERE key = 'vault_salt'")
    row = await cur.fetchone()
    return row is not None and row["value"] != ""


async def setup_vault(db, master_password: str) -> dict:
    """
    Initialise the vault: generate salt, hash password, generate TOTP secret.
    Returns {"totp_secret": str, "qr_data_uri": str}.
    Does NOT unlock the vault — user must complete 2FA verification first.
    """
    salt = os.urandom(32)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    pw_hash = hash_password_for_storage(master_password, salt)
    totp_secret = generate_totp_secret()

    # Store salt and password hash; encrypt TOTP secret with derived key
    key = derive_key(master_password, salt)
    encrypted_totp = encrypt(totp_secret, key)

    await db.execute("""
        INSERT INTO settings (key, value) VALUES ('vault_salt', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (salt_b64,))
    await db.execute("""
        INSERT INTO settings (key, value) VALUES ('vault_pw_hash', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (pw_hash,))
    await db.execute("""
        INSERT INTO settings (key, value) VALUES ('vault_totp_enc', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (encrypted_totp,))
    await db.commit()

    qr = generate_qr_data_uri(totp_secret)
    return {"totp_secret": totp_secret, "qr_data_uri": qr}


async def unlock_vault(db, master_password: str, totp_code: str) -> tuple[bool, str]:
    """
    Verify master password + TOTP code and unlock the vault.
    Returns (success: bool, error_message: str).
    """
    cur = await db.execute("SELECT value FROM settings WHERE key = 'vault_salt'")
    row = await cur.fetchone()
    if not row:
        return False, "Vault not set up"

    salt = base64.b64decode(row["value"])
    key = derive_key(master_password, salt)
    pw_hash = hash_password_for_storage(master_password, salt)

    # Verify password
    cur = await db.execute("SELECT value FROM settings WHERE key = 'vault_pw_hash'")
    stored_hash = (await cur.fetchone())["value"]
    if not hmac.compare_digest(pw_hash, stored_hash):
        return False, "Incorrect master password"

    # Decrypt and verify TOTP
    cur = await db.execute("SELECT value FROM settings WHERE key = 'vault_totp_enc'")
    enc_totp = (await cur.fetchone())["value"]
    try:
        totp_secret = decrypt(enc_totp, key)
    except Exception:
        return False, "Vault data corrupted"

    if not verify_totp(totp_secret, totp_code.strip()):
        return False, "Invalid 2FA code"

    VaultSession.unlock(key)
    return True, ""


# ─── Secret CRUD ─────────────────────────────────────────────────────────────

async def vault_list_secrets(db) -> list[dict]:
    """Return metadata for all secrets (names only, values NOT included)."""
    cur = await db.execute("""
        SELECT id, name, category, username, url, notes_preview, created_at, updated_at
        FROM vault_secrets ORDER BY category, name
    """)
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def vault_get_secret(db, secret_id: int, key: bytes) -> Optional[dict]:
    """Return a fully decrypted secret."""
    cur = await db.execute("SELECT * FROM vault_secrets WHERE id = ?", (secret_id,))
    row = await cur.fetchone()
    if not row:
        return None
    r = dict(row)
    try:
        r["password"] = decrypt(r["password_enc"], key) if r.get("password_enc") else ""
        r["notes"] = decrypt(r["notes_enc"], key) if r.get("notes_enc") else ""
    except Exception:
        return None
    del r["password_enc"]
    del r["notes_enc"]
    return r


async def vault_add_secret(db, key: bytes, name: str, category: str,
                            username: str, password: str,
                            url: str, notes: str) -> int:
    """Encrypt and store a new secret."""
    password_enc = encrypt(password, key) if password else ""
    notes_enc = encrypt(notes, key) if notes else ""
    notes_preview = notes[:30] + "..." if len(notes) > 30 else notes

    cur = await db.execute("""
        INSERT INTO vault_secrets
            (name, category, username, password_enc, url, notes_enc, notes_preview)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, category, username, password_enc, url, notes_enc, notes_preview))
    await db.commit()
    return cur.lastrowid


async def vault_update_secret(db, key: bytes, secret_id: int,
                               name: str, category: str, username: str,
                               password: str, url: str, notes: str):
    """Re-encrypt and update a secret."""
    password_enc = encrypt(password, key) if password else ""
    notes_enc = encrypt(notes, key) if notes else ""
    notes_preview = notes[:30] + "..." if len(notes) > 30 else notes

    await db.execute("""
        UPDATE vault_secrets SET
            name=?, category=?, username=?, password_enc=?,
            url=?, notes_enc=?, notes_preview=?, updated_at=datetime('now')
        WHERE id=?
    """, (name, category, username, password_enc, url, notes_enc, notes_preview, secret_id))
    await db.commit()


async def vault_delete_secret(db, secret_id: int):
    await db.execute("DELETE FROM vault_secrets WHERE id = ?", (secret_id,))
    await db.commit()


# ─── Provider key resolution ─────────────────────────────────────────────────

# Maps provider_id → vault secret name(s) to search for (case-insensitive)
PROVIDER_VAULT_NAMES: dict[str, list[str]] = {
    "anthropic": ["anthropic", "claude"],
    "openai_gpts": ["openai", "openai gpts", "gpt"],
    "gemini_gems": ["gemini", "google ai", "gemini gems"],
    "deepseek": ["deepseek"],
    "generic_api": ["api key", "generic api"],
}


async def vault_resolve_provider_key(db, provider_id: str) -> str:
    """
    Look up a provider's API key from the vault.
    Returns the decrypted password/secret if found, empty string otherwise.
    Requires the vault to be unlocked.
    """
    key = VaultSession.get_key()
    if key is None:
        return ""

    names = PROVIDER_VAULT_NAMES.get(provider_id, [provider_id])

    cur = await db.execute(
        "SELECT id, name, category FROM vault_secrets ORDER BY name"
    )
    rows = await cur.fetchall()

    for row in rows:
        secret_name = (row["name"] or "").strip().lower()
        for candidate in names:
            if candidate.lower() in secret_name:
                secret = await vault_get_secret(db, row["id"], key)
                if secret and secret.get("password"):
                    return secret["password"]

    return ""


async def vault_resolve_all_provider_keys(db) -> dict[str, str]:
    """
    Resolve API keys for all known providers from the vault.
    Returns {provider_id: api_key} for providers that have a matching secret.
    """
    key = VaultSession.get_key()
    if key is None:
        return {}

    cur = await db.execute(
        "SELECT id, name, category FROM vault_secrets ORDER BY name"
    )
    rows = await cur.fetchall()

    resolved: dict[str, str] = {}
    for provider_id, names in PROVIDER_VAULT_NAMES.items():
        if provider_id in resolved:
            continue
        for row in rows:
            secret_name = (row["name"] or "").strip().lower()
            for candidate in names:
                if candidate.lower() in secret_name:
                    secret = await vault_get_secret(db, row["id"], key)
                    if secret and secret.get("password"):
                        resolved[provider_id] = secret["password"]
                        break
            if provider_id in resolved:
                break

    return resolved
