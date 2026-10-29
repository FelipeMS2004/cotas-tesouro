# Atualiza docs/dados.json com o preço do momento do Tesouro Direto (usado pelo site)
# Roda pelo GitHub Actions a cada 15 minutos em horário de mercado
import json, os, re, unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

TITULOS = {  # apelido -> nome oficial no site do Tesouro Direto
    "Renda+ 2065": "Tesouro Renda+ Aposentadoria Extra 2065",
    "Renda+ 2045": "Tesouro Renda+ Aposentadoria Extra 2045",
    "IPCA+ 2032":  "Tesouro IPCA+ 2032",
    "LTN 2032":    "Tesouro Prefixado 2032",
}
URL = "https://www.tesourodireto.com.br/o/rentabilidade/investir"
ARQUIVO = "docs/dados.json"
TZ = ZoneInfo("America/Sao_Paulo")


def norm(txt):
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return " ".join(txt.lower().split())


def taxa(txt):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(txt or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def numero(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def baixar_json(url):
    from curl_cffi import requests as creq
    r = creq.get(url, impersonate="chrome", timeout=30,
                 headers={"Accept": "application/json, text/plain, */*",
                          "Referer": "https://www.tesourodireto.com.br/"})
    if r.status_code != 200:
        raise RuntimeError(f"Tesouro respondeu HTTP {r.status_code}")
    return r.json()


def achar_titulos(obj):
    if isinstance(obj, dict):
        if "treasuryBondName" in obj:
            yield obj
        for v in obj.values():
            yield from achar_titulos(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from achar_titulos(v)


def main():
    agora = datetime.now(TZ)
    anterior = {}
    if os.path.exists(ARQUIVO):
        with open(ARQUIVO, encoding="utf-8") as f:
            anterior = json.load(f)

    saida = dict(anterior)
    saida["consultado_em"] = agora.isoformat(timespec="seconds")
    try:
        alvo = {norm(n): ap for ap, n in TITULOS.items()}
        titulos, precificacao = {}, None
        for b in achar_titulos(baixar_json(URL)):
            ap = alvo.get(norm(b.get("treasuryBondName", "")))
            if not ap:
                continue
            titulos[ap] = {
                "nome": b.get("treasuryBondName"),
                "vencimento": str(b.get("maturityDate", ""))[:10],
                "indexador": "Prefixado" if "prefixado" in norm(ap + b.get("treasuryBondName", "")) else "IPCA+",
                "pu_compra": numero(b.get("unitaryInvestmentValue")),
                "taxa_compra": taxa(b.get("investmentProfitabilityIndexerName")),
                "pu_venda": numero(b.get("unitaryRedemptionValue")),
                "taxa_venda": taxa(b.get("redemptionProfitabilityFeeIndexerName")),
            }
            precificacao = precificacao or b.get("lastMarketPricingDate")
        if not titulos:
            raise RuntimeError("nenhum dos títulos foi encontrado no feed")

        dia = (precificacao or agora.isoformat())[:10]
        historico = anterior.get("historico", []) if anterior.get("data") == dia else []
        if not historico or historico[-1]["precificacao"] != precificacao:
            historico.append({"precificacao": precificacao,
                              "titulos": {ap: {k: t[k] for k in ("pu_compra", "taxa_compra", "pu_venda", "taxa_venda")}
                                          for ap, t in titulos.items()}})
        saida.update({"data": dia, "precificacao_td": precificacao, "ordem": list(TITULOS),
                      "titulos": titulos, "historico": historico, "erro": None})
        print(f"OK — precificação {precificacao}, {len(historico)} atualização(ões) no dia")
    except Exception as e:
        saida["erro"] = str(e)   # mantém os últimos dados bons e avisa no site
        print("FALHA:", e)

    os.makedirs("docs", exist_ok=True)
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
