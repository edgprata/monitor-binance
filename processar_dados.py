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

        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        fechamentos = {}
        volumes = {}

        for k in klines:
            if len(k) < 8:
                continue
            close_time = k[6]
            if close_time > agora_ms:
                continue

            dt_utc = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            data_str = dt_utc.strftime("%d/%m/%Y")
            data_iso = dt_utc.strftime("%Y-%m-%d")

            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
            volumes[data_iso] = float(k[7])

        return fechamentos, volumes
    except Exception:
        return {}, {}


def processar_e_salvar():
    pares = obter_pares_futuros()
    if not pares:
        print("[ERRO FATAL] Nao foi possivel consultar a API de futuros.", flush=True)
        sys.exit(1)

    print(f"-> Processando {len(pares)} contratos futuros perpetuos...", flush=True)
    lista_resultado = []
    data_recente_label = ""

    for i, par in enumerate(pares, 1):
        if i % 25 == 0 or i == len(pares):
            print(f"-> Analisando [{i}/{len(pares)}] contratos perpetuos...", flush=True)

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

        time.sleep(0.02)

    dados_finais = {
        "data_fechamento": data_recente_label,
        "ativos": lista_resultado
    }

    caminho_arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gravado para {data_recente_label} com {len(lista_resultado)} contratos futuros perpetuos!", flush=True)


if __name__ == "__main__":
    processar_e_salvar()
