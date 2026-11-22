#!/usr/bin/env python3
"""Pack verified local MiniLM and ORT Web inputs as file:// classic scripts."""
from argparse import ArgumentParser
from base64 import b64encode
from hashlib import sha256
import json
from pathlib import Path
from tarfile import open as open_tar

PART = 1_920_000
PINS = {
    "minilm.onnx": "4278337fd0ff3c68bfb6291042cad8ab363e1d9fbc43dcb499fe91c871902474",
    "minilm-tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    "onnxruntime-web.tgz": "0a38facf0672dfaaeaf352e8a9f44533732b60b4af93b9dd507fe7c2d2be437b",
}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, help="pinned ONNX, tokenizer and npm tarball")
    parser.add_argument("notices", type=Path, help="upstream license files")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, pin in PINS.items():
        if sha256((args.inputs / name).read_bytes()).hexdigest() != pin:
            parser.error(f"Transformer input SHA-256 differs: {name}")
    files = {}

    def write(name, data):
        (args.output / name).write_bytes(data)
        files[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}

    def script(name, callback, value):
        write(name, ("globalThis." + callback + "(" +
                     json.dumps(value, ensure_ascii=True, separators=(",", ":")) + ");\n").encode())

    with open_tar(args.inputs / "onnxruntime-web.tgz") as package:
        def member(name):
            file = package.extractfile("package/dist/" + name)
            if file is None:
                raise ValueError(f"Missing ORT member: {name}")
            with file:
                return file.read()

        runtime = member("ort.wasm.min.js")
        wasm = member("ort-wasm-simd-threaded.wasm")
        glue = member("ort-wasm-simd-threaded.mjs")
    # Emscripten initializes a default URL even with supplied WASM bytes.
    # A blob module has no hierarchical directory to use as its base.
    glue = glue.replace(b'new URL("./",import.meta.url)', b'new URL("./",document.baseURI)')
    glue = glue.replace(b'new URL("ort-wasm-simd-threaded.wasm",import.meta.url)',
                        b'new URL("ort-wasm-simd-threaded.wasm",document.baseURI)')
    parts = []
    for kind, raw in [("model", (args.inputs / "minilm.onnx").read_bytes()), ("wasm", wasm), ("glue", glue)]:
        for number, start in enumerate(range(0, len(raw), PART)):
            name = f"{kind}-{number:02}.js"
            parts.append(name)
            script(name, "OWLTransformerPart", [kind, number, b64encode(raw[start:start + PART]).decode()])
    vocab = json.loads((args.inputs / "minilm-tokenizer.json").read_bytes())["model"]["vocab"]
    script("assets.js", "OWLTransformer", {"parts": parts, "vocab": vocab})
    write("ort.wasm.min.js", runtime)
    for notice in ("minilm-license.txt", "onnxruntime-license.txt", "onnxruntime-notices.txt"):
        write(notice, (args.notices / notice).read_bytes())
    (args.output / "manifest.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")
    print(sum(x["bytes"] for x in files.values()))


if __name__ == "__main__":
    main()
