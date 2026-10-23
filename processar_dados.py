import os
import sys
import json
import time
from datetime import datetime, timezone
import urllib.parse
import requests
import pandas as pd

HISTORICO_DIAS = 35
PERIODO_MEDIA = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

session = requests.Session()
session.headers.update(HEADERS)


def requisicao_segura(url_alvo, params=None, timeout=12):
    """
    Executa a requisição diretamente. Se sofrer bloqueio regional (451/403/202),
    repassa automaticamente por túneis de conexão externos à região dos EUA.
    """
    url_completa = url_alvo
    if params:
        query_string = urllib.parse.urlencode(params)
        url_completa = f"{url_alvo}?{query_string}"

    # 1. Tentativa direta
    try:
        r = session.get(url_completa, timeout=timeout)
        if r.status_code == 200:
            dados = r.json()
            if isinstance(dados, (dict, list)):
                return dados
    except Exception:
        pass

    # 2. Túneis de rotação externa para contorno do bloqueio dos EUA
    gateways = [
        lambda u: f"https://corsproxy.io/?{urllib.parse.quote(u, safe='')}",
        lambda u: f"https://api.allorigins.win/raw?url={urllib.parse.quote(u, safe='')}"
    ]

    for formatar_url in gateways:
        try:
            url_tunel = formatar_url(url_completa)
            r = session.get(url_tunel, timeout=15)
            if r.status_code == 200:
                texto = r.text
                dados = json.loads(texto)
                if isinstance(dados, (dict, list)):
                    return dados
        except Exception:
            continue

    return None


def obter_pares_futuros():
    """Obtém exclusivamente os contratos perpétuos em USDT da Binance."""
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    print("-> A consultar contratos perpétuos na Binance (com rotação anti-bloqueio)...", flush=True)

    dados = requisicao_segura(url, timeout=15)
    if not dados or "symbols" not in dados:
        return []

    pares = [
        s["symbol"]
        for s in dados.get("symbols", [])
        if s.get("quoteAsset") == "USDT"
        and s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING"
    ]
    print(f"-> Sucesso! Encontrados {len(pares)} contratos futuros perpétuos.", flush=True)
    return sorted(pares)


def obter_historico(par):
    """Obtém os candles diários fechados de contratos futuros perpétuos."""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 2}

    klines = requisicao_segura(url, params=params, timeout=10)
    if not klines or not isinstance(klines, list):
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

        dt_utc = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
        data_str = dt_utc.strftime("%d/%m/%Y")
        data_iso = dt_utc.strftime("%Y-%m-%d")

        fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
        volumes[data_iso] = float(k[7])

    return fechamentos, volumes


def processar_e_salvar():
    pares = obter_pares_futuros()
    if not pares:
        print("[ERRO FATAL] Não foi possível obter os contratos futuros da Binance.", flush=True)
        sys.exit(1)

    print(f"-> Processando {len(pares)} contratos futuros perpétuos...", flush=True)
    lista_resultado = []
    data_recente_label = ""

    for i, par in enumerate(pares, 1):
        if i % 25 == 0 or i == len(pares):
            print(f"-> Analisando [{i}/{len(pares)}] contratos...", flush=True)

        try:
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
        except Exception:
            continue

        time.sleep(0.03)

    dados_finais = {
        "data_fechamento": data_recente_label,
        "ativos": lista_resultado
    }

    caminho_arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gravado para {data_recente_label} com {len(lista_resultado)} contratos futuros perpétuos!", flush=True)


if __name__ == "__main__":
    processar_e_salvar()
