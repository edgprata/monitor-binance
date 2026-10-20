File "/home/runner/work/monitor-binance/monitor-binance/processar_dados.py", line 14
    3. Executar o fluxo novamente e confirmar o visto verde (✓).
                                                             ^
SyntaxError: invalid character '✓' (U+2713)
Error: Process completed with exit code 1.
```

#### O que aconteceu tecnicamente?
Ao colar o conteúdo no ficheiro `processar_dados.py` no GitHub, foram incluídas acidentalmente algumas linhas de texto explicativo da mensagem anterior (como `3. Executar o fluxo novamente e confirmar o visto verde (✓).`) diretamente no topo do ficheiro[cite: 12]. Como essas frases não estavam delimitadas como comentários válidos de Python (usando `#` ou `"""`), o interpretador do Python tentou ler as palavras e o símbolo especial `✓` como comandos de código, gerando de imediato um **`SyntaxError`** na linha 14[cite: 12].

O nosso objetivo imediato é:
1. Limpar integralmente o ficheiro `processar_dados.py`.
2. Assegurar que o ficheiro contenha **exclusivamente código Python puro**, sem qualquer texto de instrução misturado.
3. Executar o fluxo e obter a conclusão com sucesso.

---

### 2. Panorama Geral da Solução

O ficheiro `processar_dados.py` é o coração do nosso sistema na nuvem e deve conter apenas a lógica de programação:

1. **Importações de Bibliotecas:** Carrega módulos essenciais (`requests` para comunicar com a Binance, `pandas` para cálculos estatísticos de médias e desvios, `json` para guardar os dados e `datetime` para gestão de datas).
2. **Consulta com Cabeçalhos de Proteção (`HEADERS`):** Faz pedidos à API oficial da Binance simulando um navegador moderno, evitando bloqueios automáticos nos servidores do GitHub Actions.
3. **Filtro de Candles Fechados:** Ignora a vela diária em formação e trabalha apenas com os candles encerrados às 21h (00:00 UTC).
4. **Cálculo dos Indicadores Quantitativos:**
   * Média móvel dos 20 períodos anteriores.
   * Desvio padrão e Coeficiente de Variação (CV %).
   * Variação percentual do último preço e do último volume em módulo (`abs`).
   * Classificação da operação: **`LONG`** (se Preço $\ge$ Média) ou **`SHORT`** (se Preço $<$ Média).
5. **Gravação Limpa no `dados.json`:** Guarda a estrutura pronta para a página `index.html` desenhar a tabela.

---

### 3. Código Completo e Limpo: `processar_dados.py`

Copie exatamente o bloco abaixo (apenas o que está dentro do quadro de código):

```python
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

# Cabecalho simulando um navegador moderno para evitar bloqueios no GitHub Actions
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}


def obter_pares_futuros():
    """Consulta a lista de contratos futuros perpetuos em USDT ativos."""
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> Consultando contratos futuros perpetuos na Binance...")

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

            print(f"-> Total de pares encontrados: {len(pares)}")
            return sorted(pares)

        except Exception as erro:
            print(f"[Aviso] Falha de conexao na tentativa {tentativa}: {erro}")
            time.sleep(2)

    print("[Erro] Falha ao obter simbolos da Binance apos 3 tentativas.")
    return []


def obter_historico(par):
    """Obtem apenas os candles diarios fechados de um determinado par."""
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
            if len(k) < 8 or k[6] > agora_ms:  # Descarta o candle aberto
                continue
            data_str = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%d/%m/%Y 21:00")
            data_iso = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
            volumes[data_iso] = float(k[7])
        return fechamentos, volumes
    except Exception:
        return {}, {}


def processar_e_salvar():
    """Calcula medias, desvios e gera o ficheiro dados.json."""
    pares = obter_pares_futuros()
    if not pares:
        print("[Abortado] Nenhum par encontrado para processar.")
        return

    print(f"-> Recolhendo dados para {len(pares)} ativos...")

    lista_resultado = []
    data_recente_label = ""

    for i, par in enumerate(pares, 1):
        print(f"[{i}/{len(pares)}] Processando {par}...", end="\r")
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

    caminho_arquivo = os.path.join(os.path.dirname(__file__), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gerado com {len(lista_resultado)} ativos processados!")


if __name__ == "__main__":
    processar_e_salvar()
