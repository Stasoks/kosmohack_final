from __future__ import annotations

import argparse
import json
from pathlib import Path


PAYLOAD = b"TRACE-Q ML-DSA-65 integrity checkpoint dependency proof"


def run_smoke() -> dict[str, object]:
    import oqs

    algorithm = "ML-DSA-65"
    if algorithm not in oqs.get_enabled_sig_mechanisms():
        raise RuntimeError(f"{algorithm} is not enabled by liboqs")
    with oqs.Signature(algorithm) as generator:
        public_key = generator.generate_keypair()
        private_key = generator.export_secret_key()
    # Load the exported key into a fresh signer. This proves that the runtime can
    # use externally provisioned key bytes rather than only an in-memory keypair.
    with oqs.Signature(algorithm, private_key) as signer:
        signature = signer.sign(PAYLOAD)
    with oqs.Signature(algorithm) as verifier:
        verified = bool(verifier.verify(PAYLOAD, signature, public_key))
        tamper_rejected = not bool(
            verifier.verify(PAYLOAD + b"-tampered", signature, public_key)
        )
    if not verified or not tamper_rejected:
        raise RuntimeError("ML-DSA-65 sign/verify self-test failed")
    return {
        "status": "PASS",
        "provider": "liboqs-python",
        "provider_version": oqs.oqs_python_version(),
        "native_version": oqs.oqs_version(),
        "algorithm": algorithm,
        "public_key_bytes": len(public_key),
        "private_key_bytes": len(private_key),
        "signature_bytes": len(signature),
        "verified": verified,
        "tamper_rejected": tamper_rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Real ML-DSA-65 runtime smoke test")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_smoke()
    except (Exception, SystemExit) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": type(exc).__name__, "message": str(exc)},
                indent=2,
            )
        )
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
