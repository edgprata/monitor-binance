import os
import json
import time
from datetime import datetime, timezone
import requests

BASE_URL = "https://fapi.binance.com"
HISTORICO_DIAS = 45  # Histórico para permitir consultas retroativas
PERIODO_MEDIA = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def obter_pares_futuros():
    """Consulta a lista de contratos futuros perpétuos em USDT ativos."""
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> A consultar contratos futuros perpétuos na Binance...")
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
    """Obtém candles diários fechados de um determinado par."""
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": par, "interval": "1d", "limit": HISTORICO_DIAS + 1}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        klines = r.json()
        if not isinstance(klines, list):
            return []

        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        serie = []
        for k in klines:
            if len(k) < 8 or k[6] > agora_ms:  # Descarta o candle aberto
                continue
            data_str = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%d/%m/%Y")
            data_iso = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            serie.append({
                "data": data_str,
                "data_iso": data_iso,
                "preco": float(k[4]),
                "volume": float(k[7])
            })
        return serie
    except Exception:
        return []

def processar_e_salvar():
    """Gera o banco de dados histórico para suporte retroativo."""
    pares = obter_pares_futuros()
    if not pares:
        print("[Erro] Nenhum par encontrado.")
        return

    print(f"-> A recolher dados para {len(pares)} ativos...")
    banco_ativos = {}
    conjunto_datas = set()

    for i, par in enumerate(pares, 1):
        print(f"[{i}/{len(pares)}] Processando {par}...", end="\r")
        serie = obter_historico(par)
        if len(serie) >= PERIODO_MEDIA + 1:
            banco_ativos[par] = serie
            # Adiciona apenas as datas que têm pelo menos 20 dias anteriores de histórico
            for candle in serie[PERIODO_MEDIA:]:
                conjunto_datas.add(candle["data"])
        time.sleep(0.03)

    # Ordena as datas da mais recente para a mais antiga
    datas_ordenadas = sorted(
        list(conjunto_datas),
        key=lambda d: datetime.strptime(d, "%d/%m/%Y"),
        reverse=True
    )

    dados_finais = {
        "datas_disponiveis": datas_ordenadas,
        "ativos": banco_ativos
    }

    caminho_arquivo = os.path.join(os.path.dirname(__file__), "dados.json")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False)

    print(f"\n[SUCESSO] dados.json gerado com {len(datas_ordenadas)} datas disponíveis e {len(banco_ativos)} moedas!")

if __name__ == "__main__":
    processar_e_salvar()
