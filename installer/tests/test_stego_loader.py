"""Pin the stego_loader contract: read returns None on every failure
path, returns a parsed dict only when the embedded signature verifies
against the embedded public key."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from installer.src import stego_loader

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


class ParsePayloadTests(unittest.TestCase):

    def test_empty_blob_returns_none(self):
        self.assertIsNone(stego_loader._parse_payload(b""))

    def test_short_blob_returns_none(self):
        self.assertIsNone(stego_loader._parse_payload(b"\x00" * 50))

    def test_wrong_magic_returns_none(self):
        body = b'{"a":1}'
        # Build a structurally-valid but wrong-magic blob.
        blob = (
            b"XXXX" + bytes([1]) + struct.pack("<I", len(body)) + body
            + b"\x00" * 64
        )
        self.assertIsNone(stego_loader._parse_payload(blob))

    def test_unknown_version_returns_none(self):
        body = b'{"a":1}'
        blob = (
            stego_loader._MAGIC + bytes([99])
            + struct.pack("<I", len(body)) + body + b"\x00" * 64
        )
        self.assertIsNone(stego_loader._parse_payload(blob))


class ReadFromMissingFileTests(unittest.TestCase):

    def test_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(stego_loader.read(installer_root=Path(d)))


@unittest.skipUnless(HAVE_PIL, "Pillow not available")
class EndToEndTests(unittest.TestCase):
    """Test the full producer + consumer chain by signing with a
    freshly-minted keypair, monkey-patching the loader's public key
    to match, and verifying read() returns the right dict."""

    def _make_carrier(self, path: Path):
        Image.new("RGB", (128, 128), (200, 100, 50)).save(path, format="PNG")

    def test_signed_png_round_trips_through_read(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat,
        )

        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        pub_pem = pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            carrier = d / "carrier.png"
            self._make_carrier(carrier)

            # Build a signed payload using the fresh private key.
            import json as _json
            entitlements = {"apps": [{"id": "demo-private-app", "name": "Demo"}]}
            body = _json.dumps(entitlements, sort_keys=True,
                                separators=(",", ":")).encode()
            header = (
                stego_loader._MAGIC + bytes([stego_loader._VERSION])
                + struct.pack("<I", len(body))
            )
            sig = priv.sign(header + body)
            blob = header + body + sig

            # LSB-encode the blob into the carrier.
            img = Image.open(carrier).convert("RGB")
            pixels = bytearray(img.tobytes())
            bit_idx = 0
            for byte in blob:
                for shift in range(8):
                    bit = (byte >> shift) & 1
                    pixels[bit_idx] = (pixels[bit_idx] & 0xFE) | bit
                    bit_idx += 1
            stego = d / "key.png"
            Image.frombytes("RGB", img.size, bytes(pixels)).save(stego, "PNG")

            # Monkey-patch the loader's public key to the freshly-minted
            # one so verification succeeds.
            original_pem = stego_loader._PUBLIC_KEY_PEM
            stego_loader._PUBLIC_KEY_PEM = pub_pem
            try:
                result = stego_loader.read(installer_root=d)
            finally:
                stego_loader._PUBLIC_KEY_PEM = original_pem

            self.assertIsNotNone(result)
            self.assertEqual(result["apps"][0]["id"], "demo-private-app")

    def test_signed_with_wrong_key_returns_none(self):
        # Sign with a key that DOESN'T match the embedded public --
        # loader.read should return None silently.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        priv = Ed25519PrivateKey.generate()

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            carrier = d / "carrier.png"
            self._make_carrier(carrier)

            body = b'{"apps":[{"id":"forged"}]}'
            header = (
                stego_loader._MAGIC + bytes([stego_loader._VERSION])
                + struct.pack("<I", len(body))
            )
            sig = priv.sign(header + body)
            blob = header + body + sig

            img = Image.open(carrier).convert("RGB")
            pixels = bytearray(img.tobytes())
            for i, byte in enumerate(blob):
                for shift in range(8):
                    pixels[i * 8 + shift] = (
                        (pixels[i * 8 + shift] & 0xFE)
                        | ((byte >> shift) & 1)
                    )
            stego = d / "key.png"
            Image.frombytes("RGB", img.size, bytes(pixels)).save(stego, "PNG")

            # Use the embedded (production) public key -- mismatch -> None.
            self.assertIsNone(stego_loader.read(installer_root=d))


if __name__ == "__main__":
    unittest.main()
