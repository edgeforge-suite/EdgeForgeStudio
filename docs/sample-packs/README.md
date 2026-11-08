# Synthetic Domain Sample Packs

These maintained packs demonstrate how EdgeForge Studio authors representative projects without real data, credentials, live endpoints, Knowledge Server activity, or generated code.

| Pack | Archetype | Target profile | Demonstrates |
|---|---|---|---|
| [Account Servicing](fs-account-servicing/README.md) | CRUD | `springboot-standard-enterprise` | REST/OpenAPI, fixed-width output, staging DDL, mappings, and rules |
| [Authorization Status](hc-authorization-status/README.md) | CRUD | `springboot-legacy-compatible` | REST/OpenAPI, XML/XSD output, staging DDL, mappings, and rules |
| [Claims Intake Router](ins-claims-intake-router/README.md) | passthrough-router | `springboot-legacy-compatible` | One inbound REST operation routed and transformed to three REST targets |

## Open a pack

1. Start Studio with Knowledge Assist left off.
2. Choose **Open Project**.
3. Select the pack's `project/*.edgeforge-project.json` file.
4. Review the authored state and export it through Studio when needed.

The `.edgeforge-project.json` file is the only canonical source in each pack. Files under `contracts/` and `samples/` are deterministic review copies extracted from embedded project fields. Edit the canonical project, then run:

```bash
python scripts/sample_pack_derivatives.py
python scripts/sample_pack_derivatives.py --check
```

No exported Engine package, generated application, real endpoint, customer data, or machine-specific path belongs in this directory. Engine generation and cross-repository acceptance are intentionally handled by later sample-pack slices.
