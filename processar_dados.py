import os
import json
import time
from datetime import datetime, timezone
import requests

BASE_URL = "https://fapi.binance.com"
HISTORICO_DIAS = 45
PERIODO_MEDIA = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def obter_pares_futuros():
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    print("-> A consultar contratos futuros...")
    for tentativa in range(1, 4):
        try:
            resposta = requests.get(url, headers=HEADERS, timeout=15)
            if resposta.status_code != 200:
                time.sleep(2)
                continue
            dados = resposta.json()
            if not isinstance(dados, dict) or "symbols" not in
