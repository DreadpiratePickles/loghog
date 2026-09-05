"""loghog — production logs in, an evaluation dataset out.

Phase A is stages 01 (ingest) and 02 (redact). Nothing in this package calls a
model: turning a log line into a canonical record and stripping the personal
data out of it is mechanical work, and mechanical work is code.
"""

__version__ = "0.1.0"
