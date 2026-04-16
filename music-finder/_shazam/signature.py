"""
Signature encoding/decoding for the Shazam fingerprint format.
Vendored from shazamio 0.4.0.1 (MIT License) — pydantic dependencies removed.
"""
from base64 import b64encode
from binascii import crc32
from ctypes import *
from io import BytesIO
from math import exp, sqrt
from typing import Dict, List

from .enums import FrequencyBand, SampleRate

DATA_URI_PREFIX = "data:audio/vnd.shazam.sig;base64,"


class RawSignatureHeader(LittleEndianStructure):
    _pack_ = True

    _fields_ = [
        ("magic1", c_uint32),
        ("crc32", c_uint32),
        ("size_minus_header", c_uint32),
        ("magic2", c_uint32),
        ("void1", c_uint32 * 3),
        ("shifted_sample_rate_id", c_uint32),
        ("void2", c_uint32 * 2),
        ("number_samples_plus_divided_sample_rate", c_uint32),
        ("fixed_value", c_uint32),
    ]


class FrequencyPeak:
    fft_pass_number: int = None
    peak_magnitude: int = None
    corrected_peak_frequency_bin: int = None
    sample_rate_hz: int = None

    def __init__(
        self,
        fft_pass_number: int,
        peak_magnitude: int,
        corrected_peak_frequency_bin: int,
        sample_rate_hz: int,
    ):
        self.fft_pass_number = fft_pass_number
        self.peak_magnitude = peak_magnitude
        self.corrected_peak_frequency_bin = corrected_peak_frequency_bin
        self.sample_rate_hz = sample_rate_hz

    def get_frequency_hz(self) -> float:
        return self.corrected_peak_frequency_bin * (self.sample_rate_hz / 2 / 1024 / 64)

    def get_amplitude_pcm(self) -> float:
        return sqrt(exp((self.peak_magnitude - 6144) / 1477.3) * (1 << 17) / 2) / 1024

    def get_seconds(self) -> float:
        return (self.fft_pass_number * 128) / self.sample_rate_hz


class DecodedMessage:
    sample_rate_hz: int = None
    number_samples: int = None
    frequency_band_to_sound_peaks: Dict[FrequencyBand, List[FrequencyPeak]] = None

    def encode_to_binary(self) -> bytes:
        header = RawSignatureHeader()

        header.magic1 = 0xCAFE2580
        header.magic2 = 0x94119C00
        header.shifted_sample_rate_id = int(getattr(SampleRate, "_%s" % self.sample_rate_hz)) << 27
        header.fixed_value = (15 << 19) + 0x40000
        header.number_samples_plus_divided_sample_rate = int(
            self.number_samples + self.sample_rate_hz * 0.24
        )

        contents_buf = BytesIO()

        for frequency_band, frequency_peaks in sorted(self.frequency_band_to_sound_peaks.items()):
            peaks_buf = BytesIO()

            fft_pass_number = 0

            for frequency_peak in frequency_peaks:
                assert frequency_peak.fft_pass_number >= fft_pass_number

                if frequency_peak.fft_pass_number - fft_pass_number >= 255:
                    peaks_buf.write(b"\xff")
                    peaks_buf.write(frequency_peak.fft_pass_number.to_bytes(4, "little"))
                    fft_pass_number = frequency_peak.fft_pass_number

                peaks_buf.write(bytes([frequency_peak.fft_pass_number - fft_pass_number]))
                peaks_buf.write(frequency_peak.peak_magnitude.to_bytes(2, "little"))
                peaks_buf.write(frequency_peak.corrected_peak_frequency_bin.to_bytes(2, "little"))

                fft_pass_number = frequency_peak.fft_pass_number

            contents_buf.write((0x60030040 + int(frequency_band)).to_bytes(4, "little"))
            contents_buf.write(len(peaks_buf.getvalue()).to_bytes(4, "little"))
            contents_buf.write(peaks_buf.getvalue())
            contents_buf.write(b"\x00" * (-len(peaks_buf.getvalue()) % 4))

        header.size_minus_header = len(contents_buf.getvalue()) + 8

        buf = BytesIO()
        buf.write(header)

        buf.write((0x40000000).to_bytes(4, "little"))
        buf.write((len(contents_buf.getvalue()) + 8).to_bytes(4, "little"))

        buf.write(contents_buf.getvalue())

        buf.seek(8)
        header.crc32 = crc32(buf.read()) & 0xFFFFFFFF
        buf.seek(0)
        buf.write(header)

        return buf.getvalue()

    def encode_to_uri(self) -> str:
        return DATA_URI_PREFIX + b64encode(self.encode_to_binary()).decode("ascii")
