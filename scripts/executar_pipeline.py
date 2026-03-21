from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "atualizar_populacao_ibge.py",
    "normalizar_dados.py",
    "geocodificar_complementares.py",
    "gerar_matriz_osrm.py",
    "avaliar_cenarios.py",
    "estruturar_hierarquia.py",
    "gerar_relatorio_analitico.py",
]


def main() -> None:
    for script_name in SCRIPTS:
        script_path = ROOT / "scripts" / script_name
        print(f"[pipeline] executando {script_path.relative_to(ROOT)}")
        subprocess.run([sys.executable, str(script_path)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
