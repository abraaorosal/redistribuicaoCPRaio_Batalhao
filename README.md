# redistribuicaoCPRaio_Batalhao

Painel territorial do CPRaio para análise e redistribuição operacional de municípios do Ceará com base em distância rodoviária real via OSRM.

## Conteúdo

- `index.html`: dashboard principal
- `dados/`: bases territoriais, cenários e efetivo
- `output/`: saídas geradas pela análise
- `scripts/`: pipeline Python e front-end do dashboard

## Execução local

```bash
python3 -m http.server 8000
```

Depois abra:

```text
http://127.0.0.1:8000/index.html
```

## Publicação web

O repositório está preparado para publicação estática via GitHub Pages a partir da branch `main`.

URL esperada após o deploy:

```text
https://abraaorosal.github.io/redistribuicaoCPRaio_Batalhao/
```
