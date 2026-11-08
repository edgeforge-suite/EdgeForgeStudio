# Synthetic Account Servicing

This CRUD pack shows a synthetic account model authored for `springboot-standard-enterprise`, with a REST/OpenAPI source, fixed-width end-of-day output, staging-table handoff, explicit mappings, and one allowed-values rule.

All identifiers, dates, balances, contracts, and payloads are fabricated for this pack. The API host uses `example.com`; nothing represents a real account, customer, institution, or production schema.

## Ownership

`project/fs-account-servicing.edgeforge-project.json` is the canonical Studio source. The files in `contracts/` and `samples/` are generated review copies. Do not edit them directly; update the embedded field in the canonical project and regenerate with `python scripts/sample_pack_derivatives.py`.

## Deliberately not shown

This pack does not demonstrate XML, SOAP/WSDL, Kafka, live services, Knowledge Assist, Engine generation, runtime deployment, or regulatory compliance.
