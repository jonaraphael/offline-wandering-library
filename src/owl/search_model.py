"""Convert the pinned Potion model to a quantized WordPiece table for OWL."""
from __future__ import annotations

from array import array
import base64
from hashlib import sha256
import json
from math import sqrt
import re
from struct import Struct
import sys
import unicodedata


PINS = {
    "model.safetensors": "f95ffde02ad06f63ae38eb9d400038cd5ccaf8411ec3cb650c6025113f96cbb8",
    "tokenizer.json": "e67e803f624fb4d67dea1c730d06e1067e1b14d830e2c2202569e3ef0f70bb50",
}
DIMENSIONS = 32
UPSTREAM = "https://huggingface.co/minishlab/potion-base-2M/tree/389b9f64be5aa4ae7a6bc6fe95ef20ce485ae5da"


def wordpieces(text, vocab):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    for word in re.findall(r"[^\W_]+", text, re.UNICODE):
        if len(word) > 100:
            continue
        ids = []
        position = 0
        while position < len(word):
            prefix = "##" if position else ""
            for end in range(len(word), position, -1):
                number = vocab.get(prefix + word[position:end])
                if number is not None:
                    ids.append(number)
                    position = end
                    break
            else:
                ids = []
                break
        yield from ids


class Potion:
    def __init__(self, table):
        self.table = table
        self.weights = base64.b64decode(table["weights"])
        self.scales = table["scales"]
        self.dim = len(self.scales)
        self.vocab = {word: idx for idx, word in enumerate(table["vocab"])}

    @classmethod
    def convert(cls, folder):
        inputs = {}
        for name, digest in PINS.items():
            data = (folder / ("potion-" + name)).read_bytes()
            if sha256(data).hexdigest() != digest:
                raise ValueError(f"Potion input pin differs: {name}")
            inputs[name] = data
        tokenizer = json.loads(inputs["tokenizer.json"])["model"]
        vocab = sorted(tokenizer["vocab"], key=tokenizer["vocab"].get)
        raw = inputs["model.safetensors"]
        length, = Struct("<Q").unpack_from(raw)
        meta = json.loads(raw[8:8 + length])["embeddings"]
        rows, columns = meta["shape"]
        if tokenizer["type"] != "WordPiece" or meta["dtype"] != "F32" or rows != len(vocab):
            raise ValueError("Unexpected pinned Potion model format")
        weights = array("f", raw[8 + length:])
        if sys.byteorder != "little":
            weights.byteswap()
        scales = [max(abs(value) for value in weights[column::columns]) / 127
                  for column in range(DIMENSIONS)]
        packed = bytes(round(weights[row * columns + column] / scales[column]) & 255
                       for row in range(rows) for column in range(DIMENSIONS))
        return cls({"version": 1, "upstream": UPSTREAM, "license": "MIT",
                    "vocab": vocab, "scales": scales,
                    "weights": base64.b64encode(packed).decode("ascii")})

    def encode(self, text):
        vector = [0] * self.dim
        for index in wordpieces(text[:4096], self.vocab):
            start = index * self.dim
            for column, weight in enumerate(self.weights[start:start + self.dim]):
                vector[column] += weight - 256 if weight > 127 else weight
        scaled = [value * scale for value, scale in zip(vector, self.scales)]
        norm = sqrt(sum(value * value for value in scaled))
        if not norm:
            return ""
        return base64.b64encode(bytes(round(value * 127 / norm) & 255 for value in scaled)).decode("ascii")
