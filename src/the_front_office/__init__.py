"""The Front Office — multi-sport fantasy intelligence.

Layered ports and adapters:

    domain/       models and ports. No I/O, no third-party clients.
    application/  use cases that orchestrate ports (scouting, trading, registry).
    adapters/
      inbound/    things that call us: the CLI and the web UI.
      outbound/   things we call: platform APIs, the language model, and the
                  per-sport providers that implement the SportProvider port.

Dependencies point inward only: `domain` imports nothing from the rest, and no
adapter is named anywhere in `domain` or `application`.
"""

__version__ = "0.1.0"
