"""POST /v1/speech/session : URL WebSocket signée pour Amazon Transcribe Streaming
(détection de la langue parlée entre fr-CA et en-US).

La Lambda ne reçoit ni audio ni texte : elle signe seulement l'URL (SigV4, 300 s)
que le navigateur ouvre ensuite directement vers Transcribe. Le navigateur n'a pas
d'identifiants AWS (pas d'Identity Pool), d'où cette signature côté serveur.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

import boto3
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest

from backend.common.http import json_response
from backend.common.validation import parse_json_body, validate_speech_session

LANGUAGE_CODES = {"fr": "fr-CA", "en": "en-US"}
LANGUAGE_OPTIONS = list(LANGUAGE_CODES.values())
SAMPLE_RATE = 16000
EXPIRES_IN = 300


def _credentials() -> Any:
    """Identifiants figés du rôle de la Lambda ; remplaçable dans les tests."""
    return boto3.Session().get_credentials().get_frozen_credentials()


def create_session(event: dict[str, Any], user_id: str) -> dict[str, Any]:
    lang = validate_speech_session(parse_json_body(event, allow_empty=True))
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    language_code = LANGUAGE_CODES[lang]
    query = urlencode(
        {
            "identify-language": "true",
            "language-options": ",".join(LANGUAGE_OPTIONS),
            "preferred-language": language_code,
            "media-encoding": "pcm",
            "sample-rate": str(SAMPLE_RATE),
        }
    )
    host = f"transcribestreaming.{region}.amazonaws.com:8443"
    request = AWSRequest(
        method="GET", url=f"https://{host}/stream-transcription-websocket?{query}"
    )
    SigV4QueryAuth(_credentials(), "transcribe", region, expires=EXPIRES_IN).add_auth(request)
    return json_response(
        200,
        {
            "url": request.url.replace("https://", "wss://", 1),
            "languageCode": language_code,
            "languageOptions": LANGUAGE_OPTIONS,
            "sampleRate": SAMPLE_RATE,
            "expiresIn": EXPIRES_IN,
        },
    )
