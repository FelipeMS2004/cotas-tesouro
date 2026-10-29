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
URLS = {
    "investir": "https://www.tesourodireto.com.br/o/rentabilidade/investir",
    "resgatar": "https://www.tesourodireto.com.br/o/rentabilidade/resgatar",
}
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
    """Mesma estratégia do capturar.py: se passa por Chrome e, se falhar, tenta requests."""
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
        titulos, precificacao, falhas = {}, None, []
        for lado, url in URLS.items():
            try:
                dados = baixar_json(url)
            except Exception as e:
                falhas.append(f"{lado}: {e}")
                continue
            blocos = list(achar_titulos(dados))
            print(f"{lado}: {len(blocos)} títulos no feed:", sorted(b.get("treasuryBondName", "") for b in blocos))
            if not blocos:
                falhas.append(f"{lado}: resposta sem títulos ({str(dados)[:120]})")
            for b in blocos:
                ap = alvo.get(norm(b.get("treasuryBondName", "")))
                if not ap:
                    continue
                t = titulos.setdefault(ap, {
                    "nome": b.get("treasuryBondName"),
                    "vencimento": str(b.get("maturityDate", ""))[:10],
                    "indexador": "Prefixado" if "prefixado" in norm(b.get("treasuryBondName", "")) else "IPCA+",
                    "pu_compra": None, "taxa_compra": None, "pu_venda": None, "taxa_venda": None,
                })
                valores = {
                    "pu_compra": numero(b.get("unitaryInvestmentValue")),
                    "taxa_compra": taxa(b.get("investmentProfitabilityIndexerName")),
                    "pu_venda": numero(b.get("unitaryRedemptionValue")),
                    "taxa_venda": taxa(b.get("redemptionProfitabilityFeeIndexerName")),
                }
                for campo, valor in valores.items():
                    if valor is not None:
                        t[campo] = valor
                precificacao = precificacao or b.get("lastMarketPricingDate")
        if not titulos:
            raise RuntimeError("; ".join(falhas) or "nenhum dos quatro títulos veio na resposta do Tesouro")

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
