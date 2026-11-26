"""Onisciente: a trilha do dinheiro público, da origem à prestação de contas.

"É uma trilha e não um cartório." O sistema funciona sozinho: segue cada real
pelas nove estações, deixa a fonte oficial certificar o dado e trata a
ausência de publicação como descumprimento de transparência.

Evolução do Cadê o Queijo (pasta ``cadeoqueijo/``), que segue rodando como o
primeiro domínio: a Assistência Social de Goiânia.
"""

from pathlib import Path

__version__ = "0.1.0"

RAIZ = Path(__file__).resolve().parent.parent
"""Raiz do repositório. Todo caminho do sistema parte daqui."""
