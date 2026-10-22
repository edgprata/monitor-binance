import os
import json
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

BASE_URL = "https://fapi.binance.com"
PERIODO_MEDIA = 20

# Fuso horário oficial de Brasília (UTC-3)
FUSO_BRT = timezone(timedelta(hours=-3))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

session = requests.Session()
session.headers.update(HEADERS)


def obter_pares_futuros():
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> A consultar lista de contratos futuros...", flush=True)
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
        print(f"-> Total de pares encontrados: {len(pares)}", flush=True)
        return sorted(pares)
    except Exception as e:
        print(f"[Aviso] Falha ao obter pares: {e}", flush=True)
        return []


def obter_historico(par):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": PERIODO_MEDIA + 5}
    try:
        r = session.get(url, params=params, timeout=8)
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
        print("[Erro] Nenhum par encontrado.", flush=True)
        return

    lista_resultado = []
    data_recente_label = ""

    print(f"-> A processar {len(pares)} ativos...", flush=True)

    for i, par in enumerate(pares, 1):
        if i % 30 == 0 or i == len(pares):
            print(f"-> Processando [{i}/{len(pares)}] moedas...", flush=True)

        klines = obter_historico(par)
        if not klines:
            continue

        # klines[-1] = vela diária aberta atualmente
        # klines[-2] = vela diária que fechou ontem às 21h00 em Brasília
        ultimo_fechado = klines[-2]
        anteriores = klines[-(PERIODO_MEDIA + 2):-2]

        if len(anteriores) < PERIODO_MEDIA:
            continue

        # Extrai a data da própria vela fechada retornada pela Binance (convertida para BRT)
        ts_fechamento_ms = ultimo_fechado[6]
        dt_fechamento = datetime.fromtimestamp(ts_fechamento_ms / 1000, tz=FUSO_BRT)
        data_recente_label = dt_fechamento.strftime("%d/%m/%Y")

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

        time.sleep(0.04)

    dados_finais = {
        "data_fechamento": data_recente_label,
        "ativos": lista_resultado
    }

    caminho_arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gravado com sucesso com a data: {data_recente_label} ({len(lista_resultado)} ativos)!", flush=True)


if __name__ == "__main__":
    processar_e_salvar()
