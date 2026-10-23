import os
import sys
import json
import time
from datetime import datetime, timezone
import requests
import pandas as pd

# Servidores exclusivos do mercado de Futuros Perpétuos da Binance
ENDPOINTS_FUTUROS = [
    "https://fapi.binance.com",
    "https://fapi-mm.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com"
]

HISTORICO_DIAS = 35
PERIODO_MEDIA = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

session = requests.Session()
session.headers.update(HEADERS)


def obter_pares_futuros():
    """Consulta exclusivamente contratos futuros perpétuos em USDT."""
    print("-> Consultando contratos futuros perpétuos na Binance...", flush=True)

    # 1. Tentativa direta nos servidores de futuros
    for base_url in ENDPOINTS_FUTUROS:
        url = f"{base_url}/fapi/v1/exchangeInfo"
        print(f"   Testando endpoint de futuros: {base_url}...", flush=True)
        try:
            r = session.get(url, timeout=12)
            if r.status_code == 200:
                dados = r.json()
                pares = [
                    s["symbol"]
                    for s in dados.get("symbols", [])
                    if s.get("quoteAsset") == "USDT"
                    and s.get("contractType") == "PERPETUAL"
                    and s.get("status") == "TRADING"
                ]
                if pares:
                    print(f"-> Sucesso via {base_url}! Encontrados {len(pares)} contratos futuros perpétuos.", flush=True)
                    return base_url, sorted(pares)
        except Exception:
            continue

    # 2. Proxy de túnel para futuros caso os datacenters dos EUA recebam erro 451
    print("-> Utilizando rota de túnel para acessar futuros sem bloqueio regional...", flush=True)
    gateways = [
        "https://api.codetabs.com/v1/proxy?quest=",
        "https://api.allorigins.win/raw?url="
    ]

    for gw in gateways:
        try:
            url_alvo = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            url_tunel = f"{gw}{requests.utils.quote(url_alvo)}"
            r = session.get(url_tunel, timeout=20)
            if r.status_code == 200:
                dados = r.json()
                if isinstance(dados, str):
                    dados = json.loads(dados)
                pares = [
                    s["symbol"]
                    for s in dados.get("symbols", [])
                    if s.get("quoteAsset") == "USDT"
                    and s.get("contractType") == "PERPETUAL"
                    and s.get("status") == "TRADING"
                ]
                if pares:
                    print(f"-> Sucesso via túnel! Encontrados {len(pares)} contratos futuros perpétuos.", flush=True)
                    return f"TUNEL|{gw}", sorted(pares)
        except Exception:
            continue

    return None, []


def obter_historico(origem, par):
    """Coleta velas diárias fechadas de contratos futuros perpétuos."""
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 2}

    try:
        if origem.startswith("TUNEL|"):
            gw = origem.split("|")[1]
            url_alvo = f"https://fapi.binance.com/fapi/v1/klines?symbol={par}&interval=1d&limit={HISTORICO_DIAS + 2}"
            url = f"{gw}{requests.utils.quote(url_alvo)}"
            r = session.get(url, timeout=10)
        else:
            url = f"{origem}/fapi/v1/klines"
            r = session.get(url, params=params, timeout=10)

        if r.status_code != 200:
            return {}, {}

        klines = r.json()
        if isinstance(klines, str):
            klines = json.loads(klines)

        if not isinstance(klines, list):
            return {}, {}

        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        fechamentos = {}
        volumes = {}

        for k in klines:
            if len(k) < 8:
                continue
            close_time = k[6]
            # Descarta o candle aberto de hoje
            if close_time > agora_ms:
                continue

            # Data UTC correspondente ao fechamento
            dt_utc = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            data_str = dt_utc.strftime("%d/%m/%Y")
            data_iso = dt_utc.strftime("%Y-%m-%d")

            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
            volumes[data_iso] = float(k[7])

        return fechamentos, volumes
    except Exception:
        return {}, {}


def processar_e_salvar():
    origem, pares = obter_pares_futuros()
    if not pares:
        print("[ERRO FATAL] Não foi possível consultar a API de futuros.", flush=True)
        sys.exit(1)

    print(f"-> Processando {len(pares)} contratos futuros perpétuos...", flush=True)
    lista_resultado = []
    data_recente_label = ""

    for i, par in enumerate(pares, 1):
        if i % 30 == 0 or i == len(pares):
            print(f"-> Analisando [{i}/{len(pares)}] futuros perpétuos...", flush=True)

        try:
            p, v = obter_historico(origem, par)
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
        except Exception:
            continue

        time.sleep(0.02)

    dados_finais = {
        "data_fechamento": data_recente_label,
        "ativos": lista_resultado
    }

    caminho_arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gerado para {data_recente_label} com {len(lista_resultado)} contratos futuros perpétuos!", flush=True)


if __name__ == "__main__":
    processar_e_salvar()
