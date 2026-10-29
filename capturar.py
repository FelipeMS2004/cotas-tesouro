# Captura as cotações do Tesouro Direto e acrescenta em cotacoes.csv
# Roda sozinho pelo GitHub Actions às 10h, 12h e 15h (horário de Brasília)
import csv, os, re, sys, unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

TITULOS = {  # apelido -> nome oficial no site do Tesouro Direto
    "Renda+ 2065": "Tesouro Renda+ Aposentadoria Extra 2065",
    "Renda+ 2045": "Tesouro Renda+ Aposentadoria Extra 2045",
    "IPCA+ 2032":  "Tesouro IPCA+ 2032",
    "LTN 2032":    "Tesouro Prefixado 2032",
}
URLS = {
    "venda":  "https://www.tesourodireto.com.br/o/rentabilidade/resgatar",
    "compra": "https://www.tesourodireto.com.br/o/rentabilidade/investir",
}
TZ = ZoneInfo("America/Sao_Paulo")
ARQUIVO = "cotacoes.csv"
CAMPOS = ["data", "horario", "capturado_as", "titulo", "pu_compra", "taxa_compra",
          "pu_venda", "taxa_venda", "precificacao_td", "erro"]


def norm(txt):
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return " ".join(txt.lower().split())


def baixar_json(url):
    headers = {"Accept": "application/json, text/plain, */*",
               "Referer": "https://www.tesourodireto.com.br/"}
    erros = []
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome", headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
        erros.append(f"curl_cffi HTTP {r.status_code}")
    except Exception as e:
        erros.append(f"curl_cffi: {e}")
    try:
        import requests
        headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
        erros.append(f"requests HTTP {r.status_code}")
    except Exception as e:
        erros.append(f"requests: {e}")
    raise RuntimeError(" | ".join(erros))


def achar_titulos(obj):
    if isinstance(obj, dict):
        if "treasuryBondName" in obj:
            yield obj
        for v in obj.values():
            yield from achar_titulos(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from achar_titulos(v)


def numero(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def taxa(txt):
    """'IPCA + 7,10%' -> 7.10 | '15,53%' -> 15.53"""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(txt or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def rotulo(agora):
    if os.environ.get("EVENTO") == "workflow_dispatch":
        return "manual"
    for inicio, fim, nome in [(10, 12, "10h"), (12, 15, "12h"), (15, 18, "15h")]:
        if inicio <= agora.hour < fim:
            return nome
    return "manual"


def main():
    agora = datetime.now(TZ)
    linhas = {ap: {"data": f"{agora:%Y-%m-%d}", "horario": rotulo(agora),
                   "capturado_as": f"{agora:%H:%M}", "titulo": ap, "erro": ""}
              for ap in TITULOS}
    alvo = {norm(n): ap for ap, n in TITULOS.items()}
    falhas, vistos = [], set()

    for lado, url in URLS.items():
        try:
            dados = baixar_json(url)
        except Exception as e:
            falhas.append(f"{lado}: {e}")
            continue
        for b in achar_titulos(dados):
            vistos.add(b.get("treasuryBondName", ""))
            ap = alvo.get(norm(b.get("treasuryBondName", "")))
            if not ap:
                continue
            l = linhas[ap]
            l["precificacao_td"] = b.get("lastMarketPricingDate") or l.get("precificacao_td")
            # os dois feeds trazem compra e venda; preenche o que vier, sem apagar o que já tem
            valores = {
                "pu_compra":   numero(b.get("unitaryInvestmentValue")),
                "taxa_compra": taxa(b.get("investmentProfitabilityIndexerName")),
                "pu_venda":    numero(b.get("unitaryRedemptionValue")),
                "taxa_venda":  taxa(b.get("redemptionProfitabilityFeeIndexerName")),
            }
            for campo, valor in valores.items():
                if valor is not None:
                    l[campo] = valor

    for l in linhas.values():
        if l.get("pu_venda") is None and l.get("pu_compra") is None:
            l["erro"] = "; ".join(falhas) or "título não encontrado no feed"

    novo = not os.path.exists(ARQUIVO)
    with open(ARQUIVO, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if novo:
            w.writeheader()
        w.writerows(linhas.values())

    for l in linhas.values():
        print(l)
    if falhas:
        print("FALHAS:", falhas)
    if any(l["erro"] for l in linhas.values()) and vistos:
        print("Títulos que o feed trouxe:", sorted(vistos))
    if all(l["erro"] for l in linhas.values()):
        sys.exit(1)   # faz o GitHub te mandar e-mail avisando da falha


if __name__ == "__main__":
    main()
