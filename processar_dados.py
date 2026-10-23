import os
import sys
import json
import time
from datetime import datetime, timezone
import requests
import pandas as pd

# Lista de servidores da Binance com cabeçalho de contorno regional
SERVIDORES = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com"
]

HISTORICO_DIAS = 35
PERIODO_MEDIA = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "X-Forwarded-For": "177.18.200.50"
}

session = requests.Session()
session.headers.update(HEADERS)


def obter_pares_e_endpoint():
    """Descobre o servidor acessível e obtém os contratos perpétuos em USDT."""
    print("-> Verificando conectividade com os servidores da Binance...", flush=True)

    for base_url in SERVIDORES:
        url = f"{base_url}/fapi/v1/exchangeInfo"
        print(f"   Testando endpoint: {base_url}...", flush=True)
        try:
            r = session.get(url, timeout=12)
            print(f"   Resposta HTTP: {r.status_code}", flush=True)
            if r.status_code in [200, 202]:
                dados = r.json()
                pares = [
                    s["symbol"]
                    for s in dados.get("symbols", [])
                    if s.get("quoteAsset") == "USDT"
                    and s.get("contractType") == "PERPETUAL"
                    and s.get("status") == "TRADING"
                ]
                if pares:
                    print(f"-> Sucesso via {base_url}! Encontrados {len(pares)} pares.", flush=True)
                    return base_url, sorted(pares)
        except Exception as e:
            print(f"   Falha ao conectar em {base_url}: {e}", flush=True)

    # Tentativa via Proxy Aberto caso os endpoints diretos sofram bloqueio 451
    print("-> Tentando via Gateway de Contorno...", flush=True)
    try:
        url_proxy = "https://api.allorigins.win/raw?url=" + requests.utils.quote("https://fapi.binance.com/fapi/v1/exchangeInfo")
        r = session.get(url_proxy, timeout=20)
        if r.status_code in [200, 202]:
            dados = r.json()
            pares = [
                s["symbol"]
                for s in dados.get("symbols", [])
                if s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
            ]
            if pares:
                print(f"-> Sucesso via Gateway! Encontrados {len(pares)} pares.", flush=True)
                return "PROXY", sorted(pares)
    except Exception as e:
        print(f"   Falha no gateway: {e}", flush=True)

    return None, []


def obter_historico(base_url, par):
    """
    Obtém as velas fechadas utilizando a mesma lógica UTC do script local funcional.
    """
    if base_url == "PROXY":
        url_direta = f"https://fapi.binance.com/fapi/v1/klines?symbol={par}&interval=1d&limit={HISTORICO_DIAS + 2}"
        url = "https://api.allorigins.win/raw?url=" + requests.utils.quote(url_direta)
    else:
        url = f"{base_url}/fapi/v1/klines"

    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 2} if base_url != "PROXY" else None

    try:
        r = session.get(url, params=params, timeout=10)
        if r.status_code not in [200, 202]:
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
            # Descarta a vela aberta em andamento
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
    base_url_ativo, pares = obter_pares_e_endpoint()
    if not pares:
        print("[ERRO FATAL] Impossível conectar à Binance nesta execução.", flush=True)
        sys.exit(1)

    print(f"-> A processar {len(pares)} ativos...", flush=True)
    lista_resultado = []
    data_recente_label = ""

    for i, par in enumerate(pares, 1):
        if i % 30 == 0 or i == len(pares):
            print(f"-> Processando [{i}/{len(pares)}] moedas...", flush=True)

        try:
            p, v = obter_historico(base_url_ativo, par)
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

    print(f"\n[SUCESSO] dados.json gravado para a data: {data_recente_label} ({len(lista_resultado)} ativos)!", flush=True)


if __name__ == "__main__":
    processar_e_salvar()
