# Synthetic Authorization Status

This CRUD pack shows a synthetic authorization model authored for `springboot-legacy-compatible`, with a REST/OpenAPI source, XML/XSD output, staging-table handoff, explicit mappings, and one allowed-values rule.

The external API and XML contract retain the source vocabulary `Authorization`, including the `/authorizations` routes and XML root. Studio intentionally aliases that source schema to the canonical generated entity `AuthorizationRecord`, which produces the portable unquoted SQL table name `authorization_record` instead of the reserved identifier `authorization`.

All identifiers, dates, service units, contracts, and payloads are fabricated for this pack. The API host uses `example.com`; nothing represents a real member, authorization, care record, institution, or production schema.

## Ownership

`project/hc-authorization-status.edgeforge-project.json` is the canonical Studio source. The files in `contracts/` and `samples/` are generated review copies. Do not edit them directly; update the embedded field in the canonical project and regenerate with `python scripts/sample_pack_derivatives.py`.

## Deliberately not shown

This pack does not demonstrate fixed-width files, SOAP/WSDL, Kafka, live services, Knowledge Assist, Engine generation, runtime deployment, or regulatory compliance.
