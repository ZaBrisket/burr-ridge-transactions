import time
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

UA = "burr-ridge-transactions/0.1 (mac.zabriskie@gmail.com; non-commercial research)"


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((requests.RequestException,)),
    reraise=True,
)
def get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 60) -> requests.Response:
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return r


def polite_iter(items, requests_per_second: float = 1.0):
    """Yield items at a rate-limited cadence (default 1 req/sec)."""
    delay = 1.0 / max(requests_per_second, 0.001)
    for i, x in enumerate(items):
        if i > 0:
            time.sleep(delay)
        yield x
