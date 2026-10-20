"""
Projeto: Gerador de Dados para o Dashboard Web
Autor: Parceiro de Programação
Descrição:
  1. Conecta-se à Binance Futuros.
  2. Coleta os candles diários fechados dos últimos 35 dias.
  3. Calcula Média 20d, Desvio Padrão, CV% e Variações de Volume e Preço.
  4. Salva o resultado no ficheiro leve 'dados.json' para a página Web.
"""

from datetime import datetime, timezone
import json
import time
import pandas as pd
import requests

BASE_URL = "https://fapi.binance.com"
HISTORICO_DIAS = 35
PERIODO_MEDIA = 20


def obter_pares_futuros():
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    r = requests.get(url, timeout=10)
    dados = r.json()
    return sorted(
        [
            s["symbol"]
            for s in dados["symbols"]
            if s["quoteAsset"] == "USDT"
            and s["contractType"] == "PERPETUAL"
            and s["status"] == "TRADING"
        ]
    )


def obter_historico(par):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 1}
    try:
        r = requests.get(url, params=params, timeout=10)
        klines = r.json()
        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        fechamentos = {}
        volumes = {}
        for k in klines:
            if k[6] > agora_ms:  # Descarta o candle aberto
                continue
            data_str = datetime.fromtimestamp(
                k[0] / 1000, tz=timezone.utc
            ).strftime("%d/%m/%Y %H:00")
            data_iso = datetime.fromtimestamp(
                k[0] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d")
            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
            volumes[data_iso] = float(k[7])
        return fechamentos, volumes
    except Exception:
        return {}, {}


def processar_e_salvar():
    pares = obter_pares_futuros()
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
        datas_anteriores = datas_ordenadas[-(PERIODO_MEDIA + 1) : -1]

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

        var_preco_abs = abs(((ultimo_preco - media_p) / media_p) * 100)
        var_vol_abs = (
            abs(((ultimo_vol - media_v) / media_v) * 100) if media_v > 0 else 0
        )
        operacao = "LONG" if ultimo_preco >= media_p else "SHORT"

        lista_resultado.append(
            {
                "ativo": par,
                "data_alerta": data_recente_label,
                "operacao": operacao,
                "preco": ultimo_preco,
                "volume": ultimo_vol,
                "var_preco": round(var_preco_abs, 2),
                "var_volume": round(var_vol_abs, 2),
                "cv": round(cv_p, 2),
            }
        )
        time.sleep(0.03)

    dados_finais = {
        "data_fechamento": data_recente_label,
        "ativos": lista_resultado,
    }

    with open("dados.json", "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print("\n[SUCESSO] dados.json gerado com sucesso!")


if __name__ == "__main__":
    processar_e_salvar()