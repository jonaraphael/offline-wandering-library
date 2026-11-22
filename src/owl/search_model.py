"""Convert the pinned Potion model to a quantized WordPiece table for OWL."""
from __future__ import annotations

from array import array
import base64
from functools import lru_cache
from hashlib import sha256
import json
from math import hypot
import re
from struct import Struct
import sys
import unicodedata


PINS = {
    "model.safetensors": "07609e5bd33aad37900b3fd62f4ec96f6daec88ca4d46b9d8b928bfababf6ea0",
    "tokenizer.json": "7d75cbc54318138807c401b0f0c9721117c628b39de8e8e0edb6cb17e0ee7d18",
}
DIMENSIONS = 256
UPSTREAM = "https://huggingface.co/minishlab/potion-retrieval-32M/tree/6fc8051fab2a1e0ee76689cf08c853792ac285e7"
WEIGHT_CHUNK_BYTES = 1_920_000


def piece_ids(word, vocab):
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
            return ()
    return tuple(ids)


def words(text):
    value = text.lower()
    if not value.isascii():
        value = unicodedata.normalize("NFD", value)
        value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    yield from (word for word in re.findall(r"[^\W_]+", value, re.UNICODE) if len(word) <= 100)


def semantic_text(title, excerpt, keywords):
    """Use text retained by every shard, including ones with redacted excerpts."""
    title = re.sub(r"(?: · )?Page [0-9]+$", "", title).strip()
    return " ".join((title, title, excerpt, " ".join(keywords)))


class Potion:
    def __init__(self, table, weights):
        self.table = table
        self.weights = weights
        self.dim = table["dimensions"]
        vocab = {word: idx for idx, word in enumerate(table["vocab"])}
        if self.dim != DIMENSIONS or len(weights) != len(vocab) * self.dim:
            raise ValueError("Invalid Potion weight table")
        self._pieces = lru_cache(maxsize=32768)(lambda word: piece_ids(word, vocab))
        try:
            import numpy as np
        except ImportError:
            self._numpy = None
            self._signed = tuple(Struct(f"{self.dim}b").iter_unpack(weights))
        else:
            self._numpy = np
            self._signed = np.frombuffer(weights, dtype=np.int8).reshape(-1, self.dim)

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
        return cls({"version": 2, "upstream": UPSTREAM, "license": "MIT",
                    "inputs": PINS, "dimensions": DIMENSIONS, "vocab": vocab,
                    "scales": scales}, packed)

    def _sum(self, text):
        ids = [index for word in words(text[:4096]) for index in self._pieces(word)]
        if not ids:
            return None
        if self._numpy is not None:
            return self._signed[ids].sum(axis=0, dtype=self._numpy.int32)
        return tuple(map(sum, zip(*[self._signed[index] for index in ids])))

    def encode(self, text):
        vector = self._sum(text)
        if vector is None:
            return ""
        if self._numpy is not None:
            if not vector.any():
                return ""
            signs = self._numpy.packbits(vector >= 0, bitorder="little").tobytes()
        else:
            if not any(vector):
                return ""
            bits = sum((value >= 0) << col for col, value in enumerate(vector))
            signs = bits.to_bytes(self.dim // 8, "little")
        return base64.b64encode(signs).decode("ascii")

    def unit_code(self, text):
        """Pack a unit vector as signed bytes for comparing short descriptions."""
        summed = self._sum(text)
        if summed is None:
            raise ValueError("Emergency description has no model terms")
        vector = [int(value) * scale for value, scale in zip(summed, self.table["scales"])]
        norm = hypot(*vector)
        if not norm:
            raise ValueError("Emergency description has no model terms")
        return bytes(round(127 * value / norm) & 255 for value in vector)
