"""The Front Office — multi-sport fantasy intelligence.

Layered ports and adapters:

    domain/       models and ports. No I/O, no third-party clients.
    application/  use cases over ports: scouting and trading.
    adapters/
      inbound/    things that call us: the CLI and the web UI.
      outbound/   things we call: platform APIs, the language model, and the
                  per-sport providers implementing the SportProvider port.
    bootstrap.py  the composition root: the sport registry and engine wiring.

Dependencies point inward only. `bootstrap` is the one module that names a
concrete implementation.
"""

__version__ = "0.1.0"
