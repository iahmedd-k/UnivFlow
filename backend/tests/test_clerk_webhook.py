import base64
import hashlib
import hmac
import time

from app.auth.clerk_webhook import verify_clerk_signature


def _signed_values(payload: bytes, timestamp: int) -> tuple[str, str, str]:
    message_id = "msg_test"
    secret = b"local-test-webhook-secret"
    encoded_secret = base64.b64encode(secret).decode()
    signing_secret = f"whsec_{encoded_secret}"
    signed_content = (
        message_id.encode()
        + b"."
        + str(timestamp).encode()
        + b"."
        + payload
    )
    digest = hmac.new(secret, signed_content, hashlib.sha256).digest()
    signature = f"v1,{base64.b64encode(digest).decode()}"
    return message_id, signature, signing_secret


def test_verify_clerk_signature_accepts_valid_recent_signature():
    payload = b'{"type":"user.created"}'
    timestamp = int(time.time())
    message_id, signature, signing_secret = _signed_values(payload, timestamp)

    assert verify_clerk_signature(
        payload, message_id, str(timestamp), signature, signing_secret
    )


def test_verify_clerk_signature_rejects_modified_payload():
    timestamp = int(time.time())
    message_id, signature, signing_secret = _signed_values(b'{"type":"user.created"}', timestamp)

    assert not verify_clerk_signature(
        b'{"type":"user.deleted"}',
        message_id,
        str(timestamp),
        signature,
        signing_secret,
    )


def test_verify_clerk_signature_rejects_stale_timestamp():
    timestamp = int(time.time()) - 301
    payload = b'{"type":"user.created"}'
    message_id, signature, signing_secret = _signed_values(payload, timestamp)

    assert not verify_clerk_signature(
        payload, message_id, str(timestamp), signature, signing_secret
    )


def test_verify_clerk_signature_rejects_missing_headers_or_bad_secret():
    assert not verify_clerk_signature(b"{}", None, None, None, "dev-secret")


def test_verify_clerk_signature_accepts_any_valid_v1_signature():
    payload = b'{"type":"user.created"}'
    timestamp = int(time.time())
    message_id, signature, signing_secret = _signed_values(payload, timestamp)

    assert verify_clerk_signature(
        payload,
        message_id,
        str(timestamp),
        f"v1,invalid v1,{signature.removeprefix('v1,')}",
        signing_secret,
    )
