import re
import usaddress

DEED_TYPE_MAP = {
    "warranty deed": "warranty",
    "warranty": "warranty",
    "wd": "warranty",
    "special warranty": "special_warranty",
    "swd": "special_warranty",
    "quit claim": "quit_claim",
    "quit-claim": "quit_claim",
    "quitclaim": "quit_claim",
    "qcd": "quit_claim",
    "executor": "executor",
    "executor's deed": "executor",
    "judicial sale": "judicial_sale",
    "judicial": "judicial_sale",
    "sheriff": "judicial_sale",
    "trustee": "trustee",
    "trustee's deed": "trustee",
    "beneficial interest": "beneficial_interest",
    "abi": "beneficial_interest",
}

ARMS_LENGTH_DEEDS = {"warranty", "special_warranty"}


def normalize_pin_cook(pin_raw: str | int | None) -> str | None:
    """Cook PIN: strip non-digits, zero-pad to 14."""
    if pin_raw is None:
        return None
    digits = re.sub(r"\D", "", str(pin_raw))
    if not digits:
        return None
    return digits.zfill(14)[:14]


def normalize_pin_dupage(pin_raw: str | int | None) -> str | None:
    """DuPage PIN: strip dashes/spaces, return digits-only canonical form (length varies)."""
    if pin_raw is None:
        return None
    digits = re.sub(r"\D", "", str(pin_raw))
    return digits if digits else None


def format_pin_dupage_dashed(pin_normalized: str | None) -> str | None:
    """Re-insert dashes for display: NN-NN-NNN-NNN (10 digits) or similar.
    DuPage uses 09-26-100-001 style (10 digits with 4 groups: 2-2-3-3)."""
    if not pin_normalized or len(pin_normalized) < 10:
        return pin_normalized
    p = pin_normalized
    return f"{p[0:2]}-{p[2:4]}-{p[4:7]}-{p[7:10]}"


def format_pin_cook_dashed(pin_normalized: str | None) -> str | None:
    """Re-insert dashes: NN-NN-NNN-NNN-NNNN (14-digit Cook canonical)."""
    if not pin_normalized:
        return None
    p = pin_normalized.zfill(14)[:14]
    return f"{p[0:2]}-{p[2:4]}-{p[4:7]}-{p[7:10]}-{p[10:14]}"


def normalize_address(addr_raw: str | None) -> str | None:
    if not addr_raw:
        return None
    s = re.sub(r"\s+", " ", str(addr_raw).strip().upper())
    try:
        tagged, _ = usaddress.tag(s)
    except (usaddress.RepeatedLabelError, Exception):
        return s
    parts = [
        tagged.get("AddressNumber", ""),
        tagged.get("StreetNamePreDirectional", ""),
        tagged.get("StreetName", ""),
        tagged.get("StreetNamePostType", ""),
        tagged.get("StreetNamePostDirectional", ""),
        tagged.get("OccupancyType", ""),
        tagged.get("OccupancyIdentifier", ""),
        tagged.get("PlaceName", ""),
        tagged.get("StateName", ""),
        tagged.get("ZipCode", ""),
    ]
    return " ".join(p for p in parts if p).strip() or s


def normalize_deed_type(raw: str | None) -> str:
    if not raw:
        return "other"
    key = re.sub(r"[^a-z\s'-]", "", str(raw).lower()).strip()
    for k, v in DEED_TYPE_MAP.items():
        if k in key:
            return v
    return "other"


def is_arms_length(
    deed_type: str | None,
    sale_price: float | None,
    has_filter_flags: bool,
    mydec_exemption_code: str | None = None,
    same_pin_within_365: bool = False,
) -> bool:
    if has_filter_flags:
        return False
    if deed_type not in ARMS_LENGTH_DEEDS:
        return False
    if sale_price is None or sale_price < 10_000:
        return False
    if same_pin_within_365:
        return False
    if mydec_exemption_code and mydec_exemption_code.strip().lower() not in ("", "none", "no exemption", "0"):
        return False
    return True
