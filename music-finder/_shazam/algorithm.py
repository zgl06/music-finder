"""
Shazam fingerprinting algorithm.
Vendored from shazamio 0.4.0.1 (MIT License).
Bug fix: corrected the hz_3500_5500 band condition (was unreachable in original).
"""
from copy import copy
from typing import List, Optional, Any

import numpy as np

from .enums import FrequencyBand
from .signature import DecodedMessage, FrequencyPeak

HANNING_MATRIX = np.hanning(2050)[1:-1]


class RingBuffer(list):
    def __init__(self, buffer_size: int, default_value: Any = None):
        if default_value is not None:
            list.__init__(self, [copy(default_value) for _ in range(buffer_size)])
        else:
            list.__init__(self, [None] * buffer_size)

        self.position: int = 0
        self.buffer_size: int = buffer_size
        self.num_written: int = 0

    def append(self, value: Any):
        self[self.position] = value
        self.position += 1
        self.position %= self.buffer_size
        self.num_written += 1


class SignatureGenerator:
    def __init__(self):
        self.input_pending_processing: List[int] = []
        self.samples_processed: int = 0

        self.ring_buffer_of_samples: RingBuffer = RingBuffer(buffer_size=2048, default_value=0)
        self.fft_outputs: RingBuffer = RingBuffer(buffer_size=256, default_value=[0.0 * 1025])
        self.spread_fft_output: RingBuffer = RingBuffer(buffer_size=256, default_value=[0] * 1025)

        self.MAX_TIME_SECONDS = 3.1
        self.MAX_PEAKS = 255

        self.next_signature = DecodedMessage()
        self.next_signature.sample_rate_hz = 16000
        self.next_signature.number_samples = 0
        self.next_signature.frequency_band_to_sound_peaks = {}

    def feed_input(self, s16le_mono_samples: List[int]):
        self.input_pending_processing += s16le_mono_samples

    def get_next_signature(self) -> Optional[DecodedMessage]:
        if len(self.input_pending_processing) - self.samples_processed < 128:
            return None

        while len(self.input_pending_processing) - self.samples_processed >= 128 and (
            self.next_signature.number_samples / self.next_signature.sample_rate_hz
            < self.MAX_TIME_SECONDS
            or sum(
                len(peaks)
                for peaks in self.next_signature.frequency_band_to_sound_peaks.values()
            )
            < self.MAX_PEAKS
        ):
            self.process_input(
                self.input_pending_processing[
                    self.samples_processed: self.samples_processed + 128
                ]
            )
            self.samples_processed += 128

        returned_signature = self.next_signature

        self.next_signature = DecodedMessage()
        self.next_signature.sample_rate_hz = 16000
        self.next_signature.number_samples = 0
        self.next_signature.frequency_band_to_sound_peaks = {}

        self.ring_buffer_of_samples = RingBuffer(buffer_size=2048, default_value=0)
        self.fft_outputs = RingBuffer(buffer_size=256, default_value=[0.0 * 1025])
        self.spread_fft_output = RingBuffer(buffer_size=256, default_value=[0] * 1025)

        return returned_signature

    def process_input(self, s16le_mono_samples: List[int]):
        self.next_signature.number_samples += len(s16le_mono_samples)
        for position_of_chunk in range(0, len(s16le_mono_samples), 128):
            self.do_fft(s16le_mono_samples[position_of_chunk: position_of_chunk + 128])
            self.do_peak_spreading_and_recognition()

    def do_fft(self, batch_of_128_s16le_mono_samples):
        end = self.ring_buffer_of_samples.position + len(batch_of_128_s16le_mono_samples)
        self.ring_buffer_of_samples[
            self.ring_buffer_of_samples.position: end
        ] = batch_of_128_s16le_mono_samples
        self.ring_buffer_of_samples.position += len(batch_of_128_s16le_mono_samples)
        self.ring_buffer_of_samples.position %= 2048
        self.ring_buffer_of_samples.num_written += len(batch_of_128_s16le_mono_samples)

        excerpt_from_ring_buffer = (
            self.ring_buffer_of_samples[self.ring_buffer_of_samples.position:]
            + self.ring_buffer_of_samples[: self.ring_buffer_of_samples.position]
        )

        fft_results: np.ndarray = np.fft.rfft(HANNING_MATRIX * excerpt_from_ring_buffer)
        fft_results = (fft_results.real ** 2 + fft_results.imag ** 2) / (1 << 17)
        fft_results = np.maximum(fft_results, 0.0000000001)

        self.fft_outputs.append(fft_results)

    def do_peak_spreading_and_recognition(self):
        self.do_peak_spreading()
        if self.spread_fft_output.num_written >= 46:
            self.do_peak_recognition()

    def do_peak_spreading(self):
        origin_last_fft = self.fft_outputs[self.fft_outputs.position - 1]

        tmp1 = np.tile(origin_last_fft, 3).reshape((3, -1))
        tmp1[1] = np.roll(tmp1[1], -1)
        tmp1[2] = np.roll(tmp1[2], -2)

        origin_last_fft_np = np.hstack([tmp1.max(axis=0)[:-3], origin_last_fft[-3:]])

        i1, i2, i3 = [
            (self.spread_fft_output.position + offset) % self.spread_fft_output.buffer_size
            for offset in [-1, -3, -6]
        ]

        tmp2 = np.vstack(
            [
                origin_last_fft_np,
                self.spread_fft_output[i1],
                self.spread_fft_output[i2],
                self.spread_fft_output[i3],
            ]
        )

        tmp2[1] = np.max(tmp2[:2, :], axis=0)
        tmp2[2] = np.max(tmp2[:3, :], axis=0)
        tmp2[3] = np.max(tmp2[:4, :], axis=0)

        self.spread_fft_output[i1] = tmp2[1].tolist()
        self.spread_fft_output[i2] = tmp2[2].tolist()
        self.spread_fft_output[i3] = tmp2[3].tolist()

        self.spread_fft_output.append(list(origin_last_fft_np))

    def do_peak_recognition(self):
        fft_minus_46 = self.fft_outputs[
            (self.fft_outputs.position - 46) % self.fft_outputs.buffer_size
        ]
        fft_minus_49 = self.spread_fft_output[
            (self.spread_fft_output.position - 49) % self.spread_fft_output.buffer_size
        ]

        for bin_position in range(10, 1015):
            if fft_minus_46[bin_position] >= 1 / 64 and (
                fft_minus_46[bin_position] >= fft_minus_49[bin_position - 1]
            ):
                max_neighbor_in_fft_minus_49 = 0

                for neighbor_offset in [*range(-10, -3, 3), -3, 1, *range(2, 9, 3)]:
                    max_neighbor_in_fft_minus_49 = max(
                        fft_minus_49[bin_position + neighbor_offset],
                        max_neighbor_in_fft_minus_49,
                    )

                if fft_minus_46[bin_position] > max_neighbor_in_fft_minus_49:
                    max_neighbor_in_other_adjacent_ffts = max_neighbor_in_fft_minus_49

                    for other_offset in [
                        -53,
                        -45,
                        *range(165, 201, 7),
                        *range(214, 250, 7),
                    ]:
                        max_neighbor_in_other_adjacent_ffts = max(
                            self.spread_fft_output[
                                (self.spread_fft_output.position + other_offset)
                                % self.spread_fft_output.buffer_size
                            ][bin_position - 1],
                            max_neighbor_in_other_adjacent_ffts,
                        )

                    if fft_minus_46[bin_position] > max_neighbor_in_other_adjacent_ffts:
                        fft_number = self.spread_fft_output.num_written - 46

                        peak_magnitude = (
                            np.log(max(1 / 64, fft_minus_46[bin_position])) * 1477.3 + 6144
                        )
                        peak_magnitude_before = (
                            np.log(max(1 / 64, fft_minus_46[bin_position - 1])) * 1477.3 + 6144
                        )
                        peak_magnitude_after = (
                            np.log(max(1 / 64, fft_minus_46[bin_position + 1])) * 1477.3 + 6144
                        )

                        peak_variation_1 = (
                            peak_magnitude * 2 - peak_magnitude_before - peak_magnitude_after
                        )
                        peak_variation_2 = (
                            (peak_magnitude_after - peak_magnitude_before) * 32 / peak_variation_1
                        )

                        corrected_peak_frequency_bin = bin_position * 64 + peak_variation_2

                        assert peak_variation_1 > 0

                        frequency_hz = corrected_peak_frequency_bin * (16000 / 2 / 1024 / 64)

                        if 250 < frequency_hz < 520:
                            band = FrequencyBand.hz_250_520
                        elif 520 < frequency_hz < 1450:
                            band = FrequencyBand.hz_520_1450
                        elif 1450 < frequency_hz < 3500:
                            band = FrequencyBand.hz_1450_3500
                        elif 3500 < frequency_hz <= 5500:  # fixed: was "5500 < ... <= 5500"
                            band = FrequencyBand.hz_3500_5500
                        else:
                            continue

                        if band not in self.next_signature.frequency_band_to_sound_peaks:
                            self.next_signature.frequency_band_to_sound_peaks[band] = []

                        self.next_signature.frequency_band_to_sound_peaks[band].append(
                            FrequencyPeak(
                                fft_number,
                                int(peak_magnitude),
                                int(corrected_peak_frequency_bin),
                                16000,
                            )
                        )
