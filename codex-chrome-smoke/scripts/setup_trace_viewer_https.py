from __future__ import annotations

import argparse
import ipaddress
import socket
from datetime import datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def generate_certificates(output_dir: Path, host: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow()

    root_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    root_name = _name("QA Platform Local Root CA")
    root_cert = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(root_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san_values: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(socket.gethostname()),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        san_values.append(x509.IPAddress(ipaddress.ip_address(host)))
    except ValueError:
        san_values.append(x509.DNSName(host))

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(_name(host))
        .issuer_name(root_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(root_key, hashes.SHA256())
    )

    files = {
        "qa-platform-root-ca.key": root_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "qa-platform-root-ca.crt": root_cert.public_bytes(serialization.Encoding.PEM),
        "qa-platform-server.key": server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "qa-platform-server.crt": server_cert.public_bytes(serialization.Encoding.PEM),
    }
    for filename, content in files.items():
        (output_dir / filename).write_bytes(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local CA and HTTPS certificate for Trace Viewer")
    parser.add_argument("--host", required=True, help="IP address or DNS name used by remote browsers")
    parser.add_argument("--output", type=Path, default=Path("platform-data/tls"))
    args = parser.parse_args()
    generate_certificates(args.output, args.host)
    print(f"HTTPS certificates created in {args.output.resolve()}")


if __name__ == "__main__":
    main()
