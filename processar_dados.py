import os
import json
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

BASE_URL = "https://fapi.binance.com"
HISTORICO_DIAS = 30
PERIODO_MEDIA = 20

# Fuso horário de Brasília (UTC-3)
FUSO_BRT = timezone(timedelta(hours=-3))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

# Sessão persistente para acelerar drasticamente as requisições
session = requests.Session()
session.headers.update(HEADERS)


def obter_pares_futuros():
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> A consultar lista de contratos futuros...")
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []
        dados = r.json()
        pares = [
            s["symbol"]
            for s in dados.get("symbols", [])
            if s.get("quoteAsset") == "USDT"
            and s.get("contractType") == "PERPETUAL"
            and s.get("status") == "TRADING"
        ]
        print(f"-> Total de pares encontrados: {len(pares)}")
        return sorted(pares)
    except Exception:
        return []


def obter_historico(par):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 2}
    try:
        r = session.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        klines = r.json()
        if not isinstance(klines, list) or len(klines) < PERIODO_MEDIA + 2:
            return None
        return klines
    except Exception:
        return None


def processar_e_salvar():
    pares = obter_pares_futuros()
    if not pares:
        print("[Erro] Nenhum par encontrado.")
        return

    print(f"-> A processar {len(pares)} ativos de forma acelerada...")
    lista_resultado = []
    data_recente_label = ""

    # Determina a data de fechamento com base no último candle encerrado às 21h BRT
    # Se hoje é 22/10, o último fechamento de 21h foi ontem, dia 21/10
    agora_brt = datetime.now(FUSO_BRT)
    if agora_brt.hour < 21:
        data_fechamento_oficial = (agora_brt - timedelta(days=1)).strftime("%d/%m/%Y")
    else:
        data_fechamento_oficial = agora_brt.strftime("%d/%m/%Y")

    data_recente_label = data_fechamento_oficial

    for i, par in enumerate(pares, 1):
        if i % 25 == 0 or i == len(pares):
            print(f"-> Processados {i}/{len(pares)} ativos...", flush=True)

        klines = obter_historico(par)
        if not klines:
            continue

        # klines[-1] é o candle aberto de hoje em andamento
        # klines[-2] é rigorosamente o candle que fechou ontem às 21h
        ultimo_fechado = klines[-2]
        anteriores = klines[-(PERIODO_MEDIA + 2):-2]

        if len(anteriores) < PERIODO_MEDIA:
            continue

        ultimo_preco = float(ultimo_fechado[4])
        ultimo_vol = float(ultimo_fechado[7])

        precos_ant = [float(k[4]) for k in anteriores]
        vols_ant = [float(k[7]) for k in anteriores]

        serie_p = pd.Series(precos_ant)
        serie_v = pd.Series(vols_ant)

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

    dados_finais = {
        "data_fechamento": data_recente_label,
        "ativos": lista_resultado
    }

    caminho_arquivo = os.path.join(os.path.dirname(__file__), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gerado para a data {data_recente_label} com {len(lista_resultado)} ativos em tempo recorde!")


if __name__ == "__main__":
    processar_e_salvar()
