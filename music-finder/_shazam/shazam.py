"""
Stripped Shazam recognition client.
Vendored from shazamio 0.4.0.1 (MIT License) — only recognize_song() path kept,
pydantic/schema dependencies removed, aiohttp used directly for HTTP.
"""
import pathlib
import time
import uuid
from io import BytesIO
from random import choice
from typing import Any, Dict, Union

import aiohttp
from pydub import AudioSegment

from .algorithm import SignatureGenerator
from .signature import DecodedMessage

_USER_AGENTS = [
    "Dalvik/2.1.0 (Linux; U; Android 5.0.2; VS980 4G Build/LRX22G)",
    "Dalvik/1.6.0 (Linux; U; Android 4.4.2; SM-T210 Build/KOT49H)",
    "Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-P905V Build/LMY47X)",
    "Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-N920T Build/LMY47X)",
    "Dalvik/2.1.0 (Linux; U; Android 6.0; HTC One M9 Build/MRA58K)",
    "Dalvik/2.1.0 (Linux; U; Android 6.0.1; SM-G920V Build/MMB29K)",
    "Dalvik/2.1.0 (Linux; U; Android 6.0.1; SM-G935S Build/MMB29K)",
    "Dalvik/2.1.0 (Linux; U; Android 7.0; SM-G930V Build/NRD90M)",
    "Dalvik/2.1.0 (Linux; U; Android 7.0; FRD-L09 Build/HUAWEIFRD-L09)",
]

_SEARCH_URL = (
    "https://amp.shazam.com/discovery/v5/{language}/{endpoint_country}/iphone/-/tag"
    "/{uuid_1}/{uuid_2}?sync=true&webv3=true&sampling=true"
    "&connected=&shazamapiversion=v3&sharehub=true&hubv5minorversion=v5.1&hidelb=true&video=v3"
)
_TIME_ZONE = "Europe/Moscow"


async def _load_audio(data: Union[str, pathlib.Path, bytes, bytearray, AudioSegment]) -> AudioSegment:
    if isinstance(data, (str, pathlib.Path)):
        with open(data, "rb") as f:
            raw = f.read()
        return AudioSegment.from_file(BytesIO(raw))
    if isinstance(data, (bytes, bytearray)):
        return AudioSegment.from_file(BytesIO(data))
    return data


class Shazam:
    def __init__(self, language: str = "en-US", endpoint_country: str = "GB"):
        self.language = language
        self.endpoint_country = endpoint_country

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Shazam-Platform": "IPHONE",
            "X-Shazam-AppVersion": "14.1.0",
            "Accept": "*/*",
            "Accept-Language": self.language,
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": choice(_USER_AGENTS),
        }

    @staticmethod
    def _normalize_audio(audio: AudioSegment) -> AudioSegment:
        return audio.set_sample_width(2).set_frame_rate(16000).set_channels(1)

    @staticmethod
    def _make_signature_generator(audio: AudioSegment) -> SignatureGenerator:
        gen = SignatureGenerator()
        gen.feed_input(audio.get_array_of_samples())
        gen.MAX_TIME_SECONDS = 12
        if audio.duration_seconds > 36:
            gen.samples_processed += 16000 * (int(audio.duration_seconds / 2) - 6)
        return gen

    async def recognize_song(
        self, data: Union[str, pathlib.Path, bytes, bytearray, AudioSegment]
    ) -> Dict[str, Any]:
        audio = await _load_audio(data)
        audio = self._normalize_audio(audio)
        gen = self._make_signature_generator(audio)

        if len(gen.input_pending_processing) < 128:
            return {"matches": []}

        signature = gen.get_next_signature()
        attempts = 0
        while not signature and attempts < 10:
            signature = gen.get_next_signature()
            attempts += 1

        if not signature:
            return {"matches": []}

        return await self._send_request(signature)

    async def _send_request(self, sig: DecodedMessage) -> Dict[str, Any]:
        payload = {
            "timezone": _TIME_ZONE,
            "signature": {
                "uri": sig.encode_to_uri(),
                "samplems": int(sig.number_samples / sig.sample_rate_hz * 1000),
            },
            "timestamp": int(time.time() * 1000),
            "context": {},
            "geolocation": {},
        }

        url = _SEARCH_URL.format(
            language=self.language,
            endpoint_country=self.endpoint_country,
            uuid_1=str(uuid.uuid4()).upper(),
            uuid_2=str(uuid.uuid4()).upper(),
        )

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                return await resp.json(content_type=None)
