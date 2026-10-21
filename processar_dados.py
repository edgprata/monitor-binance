import os
import json
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

# ==============================================================================
# CONFIGURAÇÕES GERAIS
# ==============================================================================
BASE_URL = "https://fapi.binance.com"
HISTORICO_DIAS = 35
PERIODO_MEDIA = 20

# Fuso horário oficial de Brasília (UTC-3)
FUSO_BRT = timezone(timedelta(hours=-3))

# Cabeçalho simulando navegador moderno para evitar bloqueios de rede no GitHub Actions
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}


def obter_pares_futuros():
    """Consulta a lista de contratos futuros perpétuos em USDT ativos."""
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> A consultar contratos futuros perpétuos...")

    for tentativa in range(1, 4):
        try:
            resposta = requests.get(url, headers=HEADERS, timeout=15)
            if resposta.status_code != 200:
                time.sleep(2)
                continue

            dados = resposta.json()
            if not isinstance(dados, dict) or "symbols" not in dados:
                time.sleep(2)
                continue

            pares = [
                s["symbol"]
                for s in dados["symbols"]
                if s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
            ]

            print(f"-> Total de pares encontrados: {len(pares)}")
            return sorted(pares)

        except Exception:
            time.sleep(2)

    return []


def obter_historico(par):
    """
    Obtém candles diários fechados convertendo o horário de encerramento para o fuso de Brasília.
    """
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 5}

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
            if len(k) < 8:
                continue

            tempo_fechamento_ms = k[6]

            # Descarta o candle aberto que ainda está em andamento
            if tempo_fechamento_ms > agora_ms:
                continue

            # Converte o timestamp de fechamento para o Horário de Brasília (UTC-3)
            data_fechamento_dt = datetime.fromtimestamp(tempo_fechamento_ms / 1000, tz=FUSO_BRT)
            data_str = data_fechamento_dt.strftime("%d/%m/%Y")
            data_iso = data_fechamento_dt.strftime("%Y-%m-%d")

            fechamentos[data_iso] = {"valor": float(k[4]), "formatada": data_str}
            volumes[data_iso] = float(k[7])

        return fechamentos, volumes

    except Exception:
        return {}, {}


def processar_e_salvar():
    """Calcula médias móveis de 20 períodos, desvios e exporta o dados.json."""
    pares = obter_pares_futuros()
    if not pares:
        print("[Erro] Nenhum par encontrado.")
        return

    print(f"-> A processar {len(pares)} ativos...")
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
        "data_fechamento": data_recente_label or datetime.now(FUSO_BRT).strftime("%d/%m/%Y"),
        "ativos": lista_resultado
    }

    caminho_arquivo = os.path.join(os.path.dirname(__file__), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCESSO] dados.json gerado com data {data_recente_label} e {len(lista_resultado)} ativos!")


if __name__ == "__main__":
    processar_e_salvar()
