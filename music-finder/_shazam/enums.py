from enum import IntEnum


class SampleRate(IntEnum):
    _8000 = 1
    _11025 = 2
    _16000 = 3
    _32000 = 4
    _44100 = 5
    _48000 = 6


class FrequencyBand(IntEnum):
    hz_0_250 = -1
    hz_250_520 = 0
    hz_520_1450 = 1
    hz_1450_3500 = 2
    hz_3500_5500 = 3
