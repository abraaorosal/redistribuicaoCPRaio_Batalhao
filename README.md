# Territorial Redistribution Analysis — Ceará

A territorial decision-support project for analyzing alternative municipality groupings using **real road-distance information** through OSRM.

The repository combines analytical scripts, territorial datasets and a static web dashboard to make geographic scenarios easier to inspect and communicate.

## Problem

Administrative or operational territories are often designed using political boundaries or straight-line distance alone. Those approximations can hide the real cost of movement between locations.

This project introduces **road-network distance** into the analysis so that territorial scenarios can be evaluated with a more realistic geographic measure.

## Project workflow

```text
Territorial datasets
        │
        ▼
Python analytical pipeline
        │
        ├── normalization
        ├── distance processing
        └── scenario generation
        │
        ▼
Generated outputs
        │
        ▼
Static analytical dashboard
```

## Main structure

```text
dados/      # Territorial, scenario and workforce datasets
scripts/    # Python analysis and dashboard-support scripts
output/     # Generated analytical outputs
index.html  # Main web dashboard
```

## Key technical concepts

- territorial data integration;
- real road-distance analysis;
- OSRM-based routing information;
- scenario comparison;
- reproducible analytical outputs;
- static web visualization for low-friction publication.

## Running the dashboard locally

A simple static server is enough to inspect the generated web interface:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://127.0.0.1:8000/index.html
```

## Engineering perspective

The important design choice in this project is the separation between **analysis** and **presentation**.

The Python layer is responsible for transforming territorial inputs into analytical outputs. The browser layer is responsible for communicating those outputs. This allows the analytical pipeline to evolve independently from the dashboard.

## Data responsibility

Territorial or workforce datasets may contain institutional information. Public versions should include only data that is authorized for disclosure and should exclude operationally sensitive fields.

## Repository

GitHub: https://github.com/abraaorosal/redistribuicaoCPRaio_Batalhao

---

**Portfolio focus:** decision support · geospatial analytics · Python · OSRM · data pipelines
