import json
import time
import random
import pathlib
import datetime
import urllib.parse
import urllib.request
import urllib.error
import email.utils

API_URL = "https://api.apiaberta.pt/v1/fuel/stations"
OUTPUT = pathlib.Path("data/fuel-prices.json")

def fetch_page(fuel, page):
    params = urllib.parse.urlencode({
        "fuel": fuel,
        "limit": 100,
        "page": page
    })
    url = API_URL + "?" + params

    for attempt in range(7):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "MotoQuest/1.0",
                    "Accept": "application/json"
                }
            )

            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)

            if not isinstance(result.get("data"), list):
                raise ValueError("Resposta invalida da API")

            return result

        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 6:
                raise

            retry_after = error.headers.get("Retry-After")
            wait = min(180, 15 * (2 ** attempt))

            if retry_after:
                try:
                    wait = max(wait, float(retry_after))
                except ValueError:
                    try:
                        retry_date = email.utils.parsedate_to_datetime(retry_after)
                        wait = max(
                            wait,
                            (retry_date - datetime.datetime.now(
                                datetime.timezone.utc
                            )).total_seconds()
                        )
                    except (TypeError, ValueError):
                        pass

            wait = min(300, max(1, wait))
            print(
                f"API ocupada (429). Aguardar {wait:.0f}s...",
                flush=True
            )
            time.sleep(wait + random.uniform(0, 2))

        except (urllib.error.URLError, TimeoutError):
            if attempt == 6:
                raise
            time.sleep(min(60, 5 * (2 ** attempt)))

def main():
    result = {
        "updated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "source": "api.apiaberta.pt",
        "fuels": {}
    }

    for fuel in ("gasoline_95", "gasoline_98"):
        first = fetch_page(fuel, 1)
        pages = int(first.get("meta", {}).get("pages", 1))

        if not 1 <= pages <= 200:
            raise ValueError("Numero de paginas invalido")

        records = list(first["data"])

        for page in range(2, pages + 1):
            time.sleep(3)
            data = fetch_page(fuel, page)
            records.extend(data["data"])

        if not records:
            raise ValueError("Sem precos para " + fuel)

        result["fuels"][fuel] = records
        print(f"{fuel}: {len(records)} registos", flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8"
    )
    temporary.replace(OUTPUT)

if __name__ == "__main__":
    main()
