# Backup do relatório — v1-relatorio-20260829

Estado congelado em 2026-08-29 (commit ed7f4d7),
com: trecho integral no G4, severidades vermelho/laranja, roxo pulsante nas
omissões, fichas+parecer espelhados nas duas contas, pizza dupla no S4.

## Restaurar tudo (gerador + os sete pareceres)
```bash
cp backup/v1-relatorio-20260829/gera_parecer_mensal_html.py src/
cp backup/v1-relatorio-20260829/parecer_2026-*.html backup/v1-relatorio-20260829/index.html docs/mensal/
```

## Restaurar só o gerador (e regerar os meses)
```bash
cp backup/v1-relatorio-20260829/gera_parecer_mensal_html.py src/
python3 src/run_mensal.py 2026-01..2026-07
```

## Alternativa por git (qualquer ponto da história)
```bash
git log --oneline -- src/gera_parecer_mensal_html.py   # achar o commit
git checkout <commit> -- src/gera_parecer_mensal_html.py
```
