# Synthetic Claims Intake Router

This passthrough-router pack shows one synthetic inbound claim operation routed and transformed to three REST targets under `springboot-legacy-compatible`.

All identifiers, dates, amounts, contracts, and payload examples are fabricated for this pack. Every API host uses `example.com`; nothing represents a real claim, policyholder, policy, carrier, or production schema.

## Ownership

`project/ins-claims-intake-router.edgeforge-project.json` is the canonical Studio source. The JSON files in `contracts/` are generated review copies. Do not edit them directly; update the embedded field in the canonical project and regenerate with `python scripts/sample_pack_derivatives.py`.

## Deliberately not shown

This pack intentionally has no entities, staging handoff, committed sample files, fixed-width files, XML, SOAP/WSDL, Kafka, live services, Knowledge Assist, Engine generation, runtime deployment, or regulatory compliance.
