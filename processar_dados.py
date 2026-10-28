import os
import sys
import json
import time
from datetime import datetime, timezone
import requests
import pandas as pd

# ==============================================================================
# CONFIGURAÇÕES GERAIS
# ==============================================================================
BINANCE_BASE = "https://fapi.binance.com"
OKX_BASE = "https://www.okx.com"

HISTORICO_DIAS = 35
PERIODO_MEDIA = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

PROXIES_ROTATIVOS = [
    None,
    {"http": "http://185.199.229.156:7492", "https": "http://185.199.229.156:7492"},
    {"http": "http://45.154.255.43:80", "https": "http://45.154.255.43:80"},
    {"http": "http://178.62.201.215:3128", "https": "http://178.62.201.215:3128"},
    {"http": "http://198.199.86.11:3128", "https": "http://198.199.86.11:3128"},
    {"http": "http://165.22.81.30:3128", "https": "http://165.22.81.30:3128"}
]

session = requests.Session()
session.headers.update(HEADERS)
proxy_binance = None


# ==============================================================================
# MÓDULO 1: COLETA BINANCE FUTURES
# ==============================================================================
def obter_pares_binance():
    global proxy_binance
    url = f"{BINANCE_BASE}/fapi/v1/exchangeInfo"
    print("-> [Binance] A testar conexao...", flush=True)

    for p in PROXIES_ROTATIVOS:
        nome = "Direto" if p is None else p["http"]
        try:
            r = session.get(url, proxies=p, timeout=8)
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
                    proxy_binance = p
                    print(f"-> [Binance] Conectado via {nome}! {len(pares)} contratos encontrados.", flush=True)
                    return sorted(pares)
        except Exception:
            continue

    # Busca proxy dinamico caso os fixos falhem
    try:
        r_p = requests.get(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=yes&anonymity=elite",
            timeout=8
        )
        if r_p.status_code == 200:
            for ip in r_p.text.strip().split("\r\n")[:8]:
                p_din = {"http": f"http://{ip}", "https": f"http://{ip}"}
                try:
                    r = session.get(url, proxies=p_din, timeout=6)
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
                            proxy_binance = p_din
                            print(f"-> [Binance] Conectado via proxy dinamico {ip}! {len(pares)} contratos.", flush=True)
                            return sorted(pares)
                except Exception:
                    continue
    except Exception:
        pass

    return []


def obter_historico_binance(par):
    url = f"{BINANCE_BASE}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 2}

    try:
        r = session.get(url, params=params, proxies=proxy_binance, timeout=8)
        if r.status_code != 200:
            return {}, {}

        klines = r.json()
        if not isinstance(klines, list):
            return {}, {}

        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        fechamentos = {}
        volumes = {}

        for k in klines:
            if len(k) < 8:
                continue
            if k[6] > agora_ms:
                continue

            dt_utc = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            data_str = dt_utc.strftime("%d/%m/%Y")
            data_iso = dt_utc.strftime("%Y-%m-%d")

            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
            volumes[data_iso] = float(k[7])

        return fechamentos, volumes
    except Exception:
        return {}, {}


def processar_binance():
    pares = obter_pares_binance()
    if not pares:
        print("[Alerta] Binance indisponivel nesta rodada.", flush=True)
        return "", []

    print(f"-> [Binance] Analisando {len(pares)} ativos...", flush=True)
    resultado = []
    data_label = ""

    for i, par in enumerate(pares, 1):
        if i % 30 == 0 or i == len(pares):
            print(f"   [Binance] Progresso: [{i}/{len(pares)}]...", flush=True)

        try:
            p, v = obter_historico_binance(par)
            if len(p) < PERIODO_MEDIA + 1:
                continue

            datas = sorted(p.keys())
            u_data = datas[-1]
            anteriores = datas[-(PERIODO_MEDIA + 1):-1]

            data_label = p[u_data]["formatada"]
            u_preco = p[u_data]["valor"]
            u_vol = v[u_data]

            serie_p = pd.Series([p[d]["valor"] for d in anteriores])
            serie_v = pd.Series([v[d] for d in anteriores])

            med_p = serie_p.mean()
            desv_p = serie_p.std()
            cv = (desv_p / med_p) * 100 if med_p > 0 else 0
            med_v = serie_v.mean()

            var_p = abs(((u_preco - med_p) / med_p) * 100) if med_p > 0 else 0
            var_v = abs(((u_vol - med_v) / med_v) * 100) if med_v > 0 else 0
            op = "LONG" if u_preco >= med_p else "SHORT"

            resultado.append({
                "ativo": par,
                "data_alerta": data_label,
                "operacao": op,
                "preco": u_preco,
                "volume": u_vol,
                "var_preco": round(var_p, 2),
                "var_volume": round(var_v, 2),
                "cv": round(cv, 2)
            })
        except Exception:
            continue

        time.sleep(0.02)

    return data_label, resultado


# ==============================================================================
# MÓDULO 2: COLETA OKX SWAP (PERPÉTUA)
# ==============================================================================
def obter_pares_okx():
    url = f"{OKX_BASE}/api/v5/public/instruments"
    params = {"instType": "SWAP"}
    print("-> [OKX] A consultar contratos perpetuos (SWAP)...", flush=True)
    try:
        r = session.get(url, params=params, timeout=12)
        if r.status_code == 200:
            dados = r.json()
            if dados.get("code") == "0":
                pares = [
                    s["instId"]
                    for s in dados.get("data", [])
                    if s.get("settleCcy") == "USDT" and s.get("state") == "live"
                ]
                print(f"-> [OKX] Encontrados {len(pares)} contratos perpetuos.", flush=True)
                return sorted(pares)
    except Exception as e:
        print(f"[Erro OKX] {e}", flush=True)
    return []


def obter_historico_okx(par):
    url = f"{OKX_BASE}/api/v5/market/candles"
    params = {"instId": par, "bar": "1D", "limit": str(HISTORICO_DIAS + 2)}

    try:
        r = session.get(url, params=params, timeout=8)
        if r.status_code != 200:
            return {}, {}

        dados = r.json()
        if dados.get("code") != "0":
            return {}, {}

        klines = dados.get("data", [])
        if not isinstance(klines, list):
            return {}, {}

        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        fechamentos = {}
        volumes = {}

        for k in klines:
            ts_abertura = int(k[0])
            ts_fechamento = ts_abertura + 86400000

            # Descarta candle aberto
            if len(k) > 8 and k[8] == "0":
                continue
            if ts_fechamento > agora_ms:
                continue

            dt_utc = datetime.fromtimestamp(ts_abertura / 1000, tz=timezone.utc)
            data_str = dt_utc.strftime("%d/%m/%Y")
            data_iso = dt_utc.strftime("%Y-%m-%d")

            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}

            # Volume em USDT
            if len(k) > 7 and float(k[7]) > 0:
                volumes[data_iso] = float(k[7])
            else:
                volumes[data_iso] = float(k[5]) * float(k[4])

        return fechamentos, volumes
    except Exception:
        return {}, {}


def processar_okx():
    pares = obter_pares_okx()
    if not pares:
        print("[Alerta] OKX indisponivel nesta rodada.", flush=True)
        return "", []

    print(f"-> [OKX] Analisando {len(pares)} ativos...", flush=True)
    resultado = []
    data_label = ""

    for i, par in enumerate(pares, 1):
        if i % 30 == 0 or i == len(pares):
            print(f"   [OKX] Progresso: [{i}/{len(pares)}]...", flush=True)

        try:
            p, v = obter_historico_okx(par)
            if len(p) < PERIODO_MEDIA + 1:
                continue

            datas = sorted(p.keys())
            u_data = datas[-1]
            anteriores = datas[-(PERIODO_MEDIA + 1):-1]

            data_label = p[u_data]["formatada"]
            u_preco = p[u_data]["valor"]
            u_vol = v[u_data]

            serie_p = pd.Series([p[d]["valor"] for d in anteriores])
            serie_v = pd.Series([v[d] for d in anteriores])

            med_p = serie_p.mean()
            desv_p = serie_p.std()
            cv = (desv_p / med_p) * 100 if med_p > 0 else 0
            med_v = serie_v.mean()

            var_p = abs(((u_preco - med_p) / med_p) * 100) if med_p > 0 else 0
            var_v = abs(((u_vol - med_v) / med_v) * 100) if med_v > 0 else 0
            op = "LONG" if u_preco >= med_p else "SHORT"

            # Remove o sufixo -SWAP para facilitar leitura na tabela
            ticker_limpo = par.replace("-SWAP", "")

            resultado.append({
                "ativo": ticker_limpo,
                "ativo_original": par,
                "data_alerta": data_label,
                "operacao": op,
                "preco": u_preco,
                "volume": u_vol,
                "var_preco": round(var_p, 2),
                "var_volume": round(var_v, 2),
                "cv": round(cv, 2)
            })
        except Exception:
            continue

        time.sleep(0.02)

    return data_label, resultado


# ==============================================================================
# GRAVAÇÃO CONSOLIDADA
# ==============================================================================
def processar_e_salvar():
    data_binance, ativos_binance = processar_binance()
    data_okx, ativos_okx = processar_okx()

    data_geral = data_binance or data_okx or datetime.now(timezone.utc).strftime("%d/%m/%Y")

    dados_finais = {
        "data_fechamento": data_geral,
        # Mantém compatibilidade com a chave raiz antiga
        "ativos": ativos_binance if ativos_binance else ativos_okx,
        "binance": {
            "data_fechamento": data_binance,
            "ativos": ativos_binance
        },
        "okx": {
            "data_fechamento": data_okx,
            "ativos": ativos_okx
        }
    }

    caminho_arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gerado!")
    print(f" -> Binance: {len(ativos_binance)} ativos ({data_binance})")
    print(f" -> OKX:     {len(ativos_okx)} ativos ({data_okx})", flush=True)


if __name__ == "__main__":
    processar_e_salvar()
