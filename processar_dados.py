import os
import sys
import json
import time
from datetime import datetime, timezone
import requests
import pandas as pd

BASE_URL = "https://fapi.binance.com"
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
proxy_ativo = None


def obter_pares_futuros():
    global proxy_ativo
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> A testar conexao aos servidores de futuros da Binance...", flush=True)

    for p in PROXIES_ROTATIVOS:
        nome_proxy = "Conexao Direta" if p is None else p["http"]
        print(f"   A tentar via: {nome_proxy}...", flush=True)
        try:
            r = session.get(url, proxies=p, timeout=8)
            print(f"   Resposta HTTP: {r.status_code}", flush=True)
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
                    proxy_ativo = p
                    print(f"-> Sucesso via {nome_proxy}! Total de {len(pares)} contratos futuros perpetuos encontrados.", flush=True)
                    return sorted(pares)
        except Exception as e:
            print(f"   Falha via {nome_proxy}: {e}", flush=True)

    print("-> A obter proxy dinamico para contorno de bloqueio...", flush=True)
    try:
        r_proxies = requests.get(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=yes&anonymity=elite",
            timeout=8
        )
        if r_proxies.status_code == 200:
            lista_dinamica = r_proxies.text.strip().split("\r\n")
            for ip_porta in lista_dinamica[:10]:
                p_dinamico = {"http": f"http://{ip_porta}", "https": f"http://{ip_porta}"}
                try:
                    r = session.get(url, proxies=p_dinamico, timeout=6)
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
                            proxy_ativo = p_dinamico
                            print(f"-> Sucesso via proxy dinamico {ip_porta}! Total de {len(pares)} contratos futuros perpetuos.", flush=True)
                            return sorted(pares)
                except Exception:
                    continue
    except Exception:
        pass

    return []


def obter_historico(par):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 2}

    try:
        r = session.get(url, params=params, proxies=proxy_ativo, timeout=8)
        if r.status_code != 200:
            return {}, {}

        klines = r.json()
        if not isinstance(klines, list):
            return {}, {}

        agora_ms = int(datetime.now(timezone.utc).
