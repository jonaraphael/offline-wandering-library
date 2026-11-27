The browser builder writes the phone catalog locally with pdf-lib 1.17.1
(`dist/pdf-lib.esm.min.js`) and @pdf-lib/fontkit 1.1.1
(`dist/fontkit.umd.min.js`). The fontkit bundle's factory is exported as an
ES module so its bundled dependencies work offline without a module loader.
Both packages are MIT licensed. Original license notices are included here.

`vera.mjs` contains the base64 bytes of Bitstream Vera Sans from ReportLab’s
`fonts/Vera.ttf`. The Python builder uses the same typeface. See
`bitstream-vera-license.txt` for the font license.
