File "/home/runner/work/monitor-binance/monitor-binance/processar_dados.py", line 1
    Traceback (most recent call last):
    ^^^^^^^^^
SyntaxError: invalid syntax. Perhaps you forgot a comma?
Error: Process completed with exit code 1.
```

#### O que aconteceu tecnicamente?
Na **linha 1** do ficheiro `processar_dados.py` foi colado acidentalmente o próprio texto do relatório de erro (`Traceback (most recent call last):`)[cite: 11]. Como esse texto em inglês não é um comando válido em Python, o interpretador encontrou um **`SyntaxError`** (erro de sintaxe) logo no primeiro caractere e encerrou a execução antes de iniciar o programa[cite: 11].

O nosso objetivo imediato é:
1. Limpar completamente o ficheiro `processar_dados.py`.
2. Colocar o código Python limpo, robusto e sem nenhum texto espúrio no topo.
3. Executar o fluxo novamente e confirmar o visto verde (✓).

---

### 2. Panorama Geral da Solução

O ficheiro `processar_dados.py` precisa de começar diretamente com os comentários em formato de docstring (`"""`) ou com as instruções de importação (`import os`, `import json`, etc.), sem nenhuma palavra solta antes.

O programa executará em 3 passos limpos:
1. **Consulta à Binance com cabeçalho de proteção (`HEADERS`):** Conecta-se à API de futuros perpétuos em USDT e descarrega a lista de moedas ativas de forma segura contra bloqueios de rede.
2. **Cálculo dos Indicadores:** Percorre as moedas, recolhe os últimos 35 candles diários fechados e calcula a Média de 20 períodos, o Desvio Padrão, o Coeficiente de Variação (CV %) e as variações de Preço e Volume.
3. **Exportação Limpa:** Grava todos os dados calculados no ficheiro `dados.json` para que o seu site no GitHub Pages leia e desenhe a tabela automaticamente.

---

### 3. Código Completo e Limpo: `processar_dados.py`

Aqui está o código completo, 100% limpo e pronto para substituir o conteúdo do ficheiro:

```python
"""
Projeto: Gerador do dados.json para o Dashboard Web
Autor: Parceiro de Programação
Descrição: Coleta candles diários fechados da Binance Futuros e calcula os sinais.
"""

import os
import json
import time
from datetime import datetime, timezone
import requests
import pandas as pd

# ==============================================================================
# CONFIGURAÇÕES GERAIS
# ==============================================================================
BASE_URL = "https://fapi.binance.com"
HISTORICO_DIAS = 35
PERIODO_MEDIA = 20

# Cabeçalho simulando um navegador moderno para evitar bloqueios de rede no GitHub Actions
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}


def obter_pares_futuros():
    """
    Etapa 1: Consulta a lista de pares perpétuos USDT com tratamento robusto de erros.
    """
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> A consultar lista de contratos futuros da Binance...")

    for tentativa in range(1, 4):
        try:
            resposta = requests.get(url, headers=HEADERS, timeout=15)
            
            if resposta.status_code != 200:
                print(f"[Aviso] Tentativa {tentativa}: Status HTTP {resposta.status_code}")
                time.sleep(2)
                continue

            dados = resposta.json()

            if not isinstance(dados, dict) or "symbols" not in dados:
                print(f"[Aviso] Resposta sem chave 'symbols'")
                time.sleep(2)
                continue

            pares = [
                s["symbol"]
                for s in dados["symbols"]
                if s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
            ]

            print(f"-> Total de pares encontrados com sucesso: {len(pares)}")
            return sorted(pares)

        except Exception as erro:
            print(f"[Aviso] Falha de conexão na tentativa {tentativa}: {erro}")
            time.sleep(2)

    print("[Erro Crítico] Não foi possível obter os símbolos da Binance após 3 tentativas.")
    return []


def obter_historico(par):
    """
    Etapa 2: Obtém as velas diárias fechadas de um par com cabeçalho de proteção.
    """
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 1}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return {}, {}
            
        klines = r.json()
        if not isinstance(klines, list):
            return {}, {}

        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        fechamentos = {}
        volumes = {}
        for k in klines:
            if len(k) < 8 or k[6] > agora_ms:  # Descarta o candle aberto em movimento
                continue
            data_str = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%d/%m/%Y 21:00")
            data_iso = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
            volumes[data_iso] = float(k[7])
        return fechamentos, volumes
    except Exception:
        return {}, {}


def processar_e_salvar():
    """
    Etapa 3: Calcula médias, desvios e gera o arquivo dados.json.
    """
    pares = obter_pares_futuros()
    if not pares:
        print("[Abortado] Nenhum par disponível para processamento.")
        return

    print(f"-> A recolher dados para {len(pares)} ativos...")

    lista_resultado = []
    data_recente_label = ""

    for i, par in enumerate(pares, 1):
        print(f"[{i}/{len(pares)}] {par}...", end="\r")
        p, v = obter_historico(par)
        if len(p) < PERIODO_MEDIA + 1:
            continue

        datas_ordenadas = sorted(p.keys())
        ultima_data = datas_ordenadas[-1]
        datas_anteriores = datas_ordenadas[-(PERIODO_MEDIA + 1):-1]

        data_recente_label = p[ultima_data]["formatada"]
        ultimo_preco = p[ultima_data]["valor"]
        ultimo_vol = v[ultima_data]

        precos_anteriores = [p[d]["valor"] for d in datas_anteriores]
        volumes_anteriores = [v[d] for d in datas_anteriores]

        serie_p = pd.Series(precos_anteriores)
        serie_v = pd.Series(volumes_anteriores)

        media_p = serie_p.mean()
        desvio_p = serie_p.std()
        cv_p = (desvio_p / media_p) * 100 if media_p > 0 else 0
        media_v = serie_v.mean()

        var_preco_abs = abs(((ultimo_preco - media_p) / media_p) * 100) if media_p > 0 else 0
        var_vol_abs = abs(((ultimo_vol - media_v) / media_v) * 100) if media_v > 0 else 0
        operacao = "LONG" if ultimo_preco >= media_p else "SHORT"

        lista_resultado.append({
            "ativo": par,
            "data_alerta": data_recente_label,
            "operacao": operacao,
            "preco": ultimo_preco,
            "volume": ultimo_vol,
            "var_preco": round(var_preco_abs, 2),
            "var_volume": round(var_vol_abs, 2),
            "cv": round(cv_p, 2)
        })
        time.sleep(0.03)

    dados_finais = {
        "data_fechamento": data_recente_label or datetime.now().strftime("%d/%m/%Y"),
        "ativos": lista_resultado
    }

    # Salva o arquivo dados.json na pasta do projeto
    caminho_arquivo = os.path.join(os.path.dirname(__file__), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gerado com {len(lista_resultado)} ativos processados!")


if __name__ == "__main__":
    processar_e_salvar()
