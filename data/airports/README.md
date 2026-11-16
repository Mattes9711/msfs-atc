# Test airports: not in the repository

The tests fly between Hamburg (EDDH) and Munich (EDDM). Their airports are JSON files exported with
`python -m atc.airport.export EDDH EDDM` from your own Little Navmap database, which is built from the scenery you
installed in MSFS. Because that data comes from licensed scenery (payware add-ons included), the files are not in
the public repository (`.gitignore`), and must never be bundled with the app or published.

Without them, the tests that need them are skipped (`tests/conftest.py`). To run them all, export the two airports
here with the command above. A release build reads the user's own Little Navmap database instead (see BUILD.md).
