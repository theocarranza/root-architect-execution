# <project-name>

[![CI](https://github.com/<owner>/<repo>/actions/workflows/<workflow>.yml/badge.svg?branch=<default-branch>)](https://github.com/<owner>/<repo>/actions/workflows/<workflow>.yml)
[![Runtime](https://img.shields.io/badge/<runtime>-<version>-blue.svg)](runtime-url)
[![Documentation](https://img.shields.io/badge/docs-project_documentation-informational.svg)](./docs/README.md)

<!-- Add only badges that communicate maintained, verifiable project state. -->

<One sentence explaining what the project is, who it is for, and the primary value it provides.>

> **Core principle:** <one memorable architectural/product rule>

## Why this exists

<Describe the problem. Explain why existing/simple approaches are insufficient. Keep this about the problem, not implementation detail.>

```text
<small ASCII diagram showing the conceptual solution>
```

## Documentation

The complete project documentation is available under [`docs/`](./docs/README.md).

| Area         | Documentation                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------------- |
| Product      | [`docs/00-product/`](./docs/00-product/) — vision, requirements, glossary                          |
| Architecture | [`docs/01-architecture/`](./docs/01-architecture/) — context, architecture, data model, ADRs       |
| Design       | [`docs/02-design/`](./docs/02-design/) — APIs/interfaces, components, workflows                    |
| Engineering  | [`docs/03-engineering/`](./docs/03-engineering/) — development, testing, standards, dependencies   |
| Operations   | [`docs/04-operations/`](./docs/04-operations/) — deployment, environments, observability, runbooks |
| Security     | [`docs/05-security/`](./docs/05-security/) — security model, threats, privacy                      |
| Delivery     | [`docs/06-delivery/`](./docs/06-delivery/) — roadmap, releases, changelog                          |
| Guides       | [`docs/07-guides/`](./docs/07-guides/) — onboarding, usage, troubleshooting                        |

## Architecture at a glance

<Explain the architecture in 1–2 paragraphs.>

```text
<ASCII component/data-flow diagram>
```

See [`docs/01-architecture/architecture.md`](./docs/01-architecture/architecture.md).

## Features / capabilities

- <capability>
- <capability>
- <capability>

## Requirements

| Requirement       | Version / Notes |
| ----------------- | --------------- |
| <runtime>         | <version>       |
| <dependency/tool> | <requirement>   |

## Installation

```bash
<installation commands>
```

## Quick start

```bash
<smallest useful example>
```

<Describe the expected result.>

## How it works

```text
<ASCII happy-path workflow>
```

See [`docs/02-design/workflows.md`](./docs/02-design/workflows.md).

## Repository layout

| Path                 | Purpose                    |
| -------------------- | -------------------------- |
| [`docs/`](./docs/)   | Project documentation      |
| [`src/`](./src/)     | Application/library source |
| [`tests/`](./tests/) | Automated tests            |
| <path>               | <purpose>                  |

## Configuration

<Document only the most important configuration here. Link to detailed operations docs for the rest.>

| Variable / Setting | Required | Purpose   |
| ------------------ | -------- | --------- |
| `<NAME>`           | yes/no   | <purpose> |

## Development

```bash
<setup commands>
<development command>
```

See [`docs/03-engineering/development.md`](./docs/03-engineering/development.md).

## Testing

```bash
<test commands>
```

State what these tests prove and, equally importantly, what additional gates are required.

See [`docs/03-engineering/testing.md`](./docs/03-engineering/testing.md).

## Deployment

<Short deployment description and primary command/link.>

See [`docs/04-operations/deployment.md`](./docs/04-operations/deployment.md).

## Security

<Summarize the project's trust/security model and how vulnerabilities should be handled. Do not put secrets or sensitive operational details here.>

See [`docs/05-security/security.md`](./docs/05-security/security.md).

## Project status

<Current maturity/status. Link to the maintained roadmap rather than maintaining a second detailed roadmap here.>

See [`docs/06-delivery/roadmap.md`](./docs/06-delivery/roadmap.md).

## Contributing

<Short contribution contract: authoritative sources, tests, generated artifacts, docs.>

See [`docs/07-guides/onboarding.md`](./docs/07-guides/onboarding.md).

## License

<License name and link to LICENSE file. Remove this section until a license actually exists.>

---

For the complete project model, start with **[`docs/README.md`](./docs/README.md)**.
