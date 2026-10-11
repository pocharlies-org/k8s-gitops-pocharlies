#!/usr/bin/env python3
"""El split FIJO del corpus del juez (SC-2264): cada caso de `tests/fixtures/juez/<caso>/` cae en
entrenamiento (20 %), validacion (40 %) o prueba (40 %) segun un hash de SU NOMBRE. No depende de
cuantos casos haya ni de su orden: añadir un caso nunca mueve a otro.

- entrenamiento: de aqui salen los ejemplos de la rubrica (`EJEMPLOS_RUBRICA` de review.py).
- validacion: donde se itera la rubrica y las reglas (una regla entra solo si aqui no suben los falsos PASA).
- prueba: no se toca al iterar; se mide por version.

Uso: `juez_split.py <split|todos> <corpus> <destino>` copia a `<destino>` los casos de ese split (y el
`ARCHITECTURE.md` comun) para `review.py --evalua <destino>`; sirve igual con el review.py de `main`,
que no conoce el split."""
import hashlib
import shutil
import sys
from pathlib import Path

SPLITS = ('entrenamiento', 'validacion', 'prueba')


def split_de(nombre):
    n = int(hashlib.sha256(nombre.encode('utf-8')).hexdigest(), 16) % 100
    return SPLITS[0] if n < 20 else SPLITS[1] if n < 60 else SPLITS[2]


def casos_de(corpus, split):
    """Los directorios-caso del corpus que caen en `split` (`todos` = todos), por orden de nombre."""
    return sorted(d for d in Path(corpus).iterdir() if d.is_dir() and split in ('todos', split_de(d.name)))


def main(argv):
    if len(argv) != 3 or argv[0] not in SPLITS + ('todos',):
        print(f'uso: juez_split.py <{"|".join(SPLITS)}|todos> <corpus> <destino>', file=sys.stderr)
        return 2
    split, corpus, destino = argv[0], Path(argv[1]), Path(argv[2])
    casos = casos_de(corpus, split)
    if not casos:
        print(f'::error::ningun caso en el split {split} de {corpus}')
        return 1
    destino.mkdir(parents=True, exist_ok=True)
    for caso in casos:
        shutil.copytree(caso, destino / caso.name)
    if (corpus / 'ARCHITECTURE.md').is_file():
        shutil.copy(corpus / 'ARCHITECTURE.md', destino / 'ARCHITECTURE.md')
    print(f'split {split}: {len(casos)} casos en {destino}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
