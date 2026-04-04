"""
cert_utils.py — Self-signed TLS certificate generation for DungeonPy DM server.

On first DM launch, call ensure_cert() to auto-generate a cert + private key
that persist across sessions.  Players connect with --insecure to skip
certificate verification (appropriate for a closed group using a self-signed cert).
"""

import datetime
import os


def ensure_cert(cert_path: str = "dm_cert.pem",
                key_path:  str = "dm_key.pem") -> tuple[str, str]:
    """
    Return (cert_path, key_path).  If either file is missing, generate a fresh
    self-signed RSA-2048 / SHA-256 cert valid for 10 years and save both files.
    """
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise RuntimeError(
            "The 'cryptography' package is required for TLS support.\n"
            "Install it with:  pip install cryptography"
        )

    print("[DungeonPy] Generating self-signed TLS certificate ...")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "DungeonPy"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))

    print(f"[DungeonPy] Certificate saved to {cert_path} / {key_path}")
    print("[DungeonPy] Players should connect with --insecure to accept this cert.")
    return cert_path, key_path
