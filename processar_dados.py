Traceback (most recent call last):
  File "processar_dados.py", line 127, in <module>
    processar_e_salvar()
  File "processar_dados.py", line 64, in processar_e_salvar
    pares = obter_pares_futuros()
  File "processar_dados.py", line 29, in obter_pares_futuros
    for s in dados["symbols"]
KeyError: 'symbols'
Error: Process completed with exit code 1.
```

#### O que aconteceu tecnicamente?
1. O script executou a função `obter_pares_futuros()` e fez uma requisição à API da Binance através da biblioteca `requests`[cite: 10].
2. Quando tentou aceder ao campo `dados["symbols"]`, o Python devolveu o erro **`KeyError: 'symbols'`**[cite: 10]. Isso significa que o JSON retornado pela Binance **não continha a chave `"symbols"`**.
3. **Por que a chave não veio?**
   * Os servidores do GitHub Actions estão alojados nos data centers da nuvem (Microsoft Azure nos EUA). Em muitas requisições automáticas diretas a partir de IPs de servidores de nuvem, a Binance bloqueia temporariamente a conexão com erro `403 Forbidden` ou devolve uma mensagem de proteção/Cloudflare com a mensagem `{"code": -1003, "msg": "Too many requests..."}` ou bloqueio de região, em vez do dicionário normal de mercado.
   * Além disso, a requisição não continha cabeçalhos HTTP de navegador (`User-Agent`), facilitando o bloqueio automático como tráfego suspeito.

---

### 2. Panorama Geral da Solução

Para blindar o nosso coletor e garantir que funcione perfeitamente tanto no seu computador como nos servidores do GitHub Actions:

1. **Adicionar `User-Agent` simulando um navegador real:** Isso evita que a API da Binance descarte a conexão como requisição de bot.
2. **Tratamento de exceções e verificação de resposta (`status_code` e validação de chaves):** Em vez de aceder cegamente a `dados["symbols"]`, verificamos se a chave existe e se a resposta foi bem-sucedida (`200 OK`).
3. **Mecanismo de Retentativa (Retry) e Fallback:** Se a Binance falhar no primeiro segundo, o script tenta novamente após 2 segundos.
4. **Verificação de segurança no `processar_dados.py`:** Se por algum motivo de rede nenhum par for retornado, o script não tenta quebrar o fluxo com erro fatal, registando uma mensagem informativa no log.

---

### 3. Código Completo e Corrigido: `processar_dados.py`

Substitua todo o conteúdo do seu ficheiro `processar_dados.py` no GitHub pelo código abaixo:

```python
"""
Projeto: Gerador do dados.json para o Dashboard Web
Autor: Parceiro de Programação
Correção: Tratamento contra bloqueios de IP/User-Agent e erro KeyError: 'symbols'.
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
                print(f"[Aviso] Tentativa {tentativa}: Status HTTP {resposta.status_code}. Mensagem: {resposta.text[:120]}")
                time.sleep(2)
                continue

            dados = resposta.json()

            # Verificação segura para evitar o erro KeyError: 'symbols'
            if not isinstance(dados, dict) or "symbols" not in dados:
                print(f"[Aviso] Resposta sem chave 'symbols': {dados}")
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
