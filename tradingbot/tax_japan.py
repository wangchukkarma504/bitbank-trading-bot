"""Japan Crypto Tax (確定申告 / 雑所得) Tracker & CSV Exporter for Bitbank."""

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import io
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger("JapanTax")
JST = timezone(timedelta(hours=9))


@dataclass
class TaxProfile:
    tax_year: int = 2026
    employment_type: str = "salary"  # "salary" (¥200k rule) or "other"
    annual_salary_jpy: float = 0.0
    other_misc_income_jpy: float = 0.0
    filing_threshold_jpy: float = 200000.0
    taxpayer_name: str = ""
    tax_office: str = ""


def load_tax_profile(path: str = "tax_profile.json") -> TaxProfile:
    default_year = datetime.now(JST).year
    prof = TaxProfile(tax_year=default_year)
    if not path or not os.path.exists(path):
        return prof
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        prof.tax_year = int(data.get("tax_year") or default_year)
        prof.employment_type = str(data.get("employment_type") or "salary")
        prof.annual_salary_jpy = float(data.get("annual_salary_jpy") or 0.0)
        prof.other_misc_income_jpy = float(data.get("other_misc_income_jpy") or 0.0)
        prof.filing_threshold_jpy = float(data.get("filing_threshold_jpy") or 200000.0)
        prof.taxpayer_name = str(data.get("taxpayer_name") or "")
        prof.tax_office = str(data.get("tax_office") or "")
    except Exception as e:
        logger.warning(f"Could not load tax profile: {e}")
    return prof


def save_tax_profile(profile: TaxProfile, path: str = "tax_profile.json") -> None:
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(profile), f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save tax profile: {e}")


def _salary_deduction_jpy(salary: float) -> float:
    """Approximate Japan Employment Income Deduction (給与所得控除)."""
    if salary <= 0:
        return 0.0
    if salary <= 1_625_000:
        return 550_000.0
    if salary <= 1_800_000:
        return salary * 0.40 - 100_000.0
    if salary <= 3_600_000:
        return salary * 0.30 + 80_000.0
    if salary <= 6_600_000:
        return salary * 0.20 + 440_000.0
    if salary <= 8_500_000:
        return salary * 0.10 + 1_100_000.0
    return 1_950_000.0


def _national_income_tax(taxable_income: float) -> float:
    """Japan NTA progressive income tax + 2.1% reconstruction surtax."""
    if taxable_income <= 0:
        return 0.0
    brackets: List[Tuple[float, float, float]] = [
        (1_949_000, 0.05, 0.0),
        (3_299_000, 0.10, 97_500.0),
        (6_949_000, 0.20, 427_500.0),
        (8_999_000, 0.23, 636_000.0),
        (17_999_000, 0.33, 1_536_000.0),
        (39_999_000, 0.40, 2_796_000.0),
        (float("inf"), 0.45, 4_796_000.0),
    ]
    base_tax = 0.0
    for limit, rate, deduction in brackets:
        if taxable_income <= limit:
            base_tax = max(0.0, taxable_income * rate - deduction)
            break
    return base_tax * 1.021


def estimate_crypto_tax_jpy(
    net_crypto_profit_jpy: float,
    profile: TaxProfile,
) -> Dict[str, Any]:
    """Estimate Japan national + 10% resident tax attributable to crypto profit."""
    net_misc = max(0.0, net_crypto_profit_jpy) + max(0.0, profile.other_misc_income_jpy)
    threshold = max(0.0, profile.filing_threshold_jpy)
    threshold_pct = min(100.0, (net_misc / threshold * 100.0)) if threshold > 0 else 100.0

    if profile.employment_type == "salary":
        national_filing_required = net_misc > threshold
    else:
        national_filing_required = net_crypto_profit_jpy > 0

    filing_window = f"Feb 16 – Mar 15, {profile.tax_year + 1}"
    if net_crypto_profit_jpy <= 0:
        advice = (
            f"No tax filing needed for {profile.tax_year}: your YTD crypto net profit is "
            f"¥{net_crypto_profit_jpy:,.0f} (0 or negative), so ¥0 tax is owed and neither 確定申告 "
            f"nor 住民税申告 is required for crypto."
        )
        return {
            "estimated_tax_jpy": 0.0,
            "effective_rate_pct": 0.0,
            "national_filing_required": False,
            "resident_tax_note": "No taxable profit recorded.",
            "filing_advice": advice,
            "threshold_pct": round(threshold_pct, 1),
            "remaining_to_threshold_jpy": round(max(0.0, threshold - net_misc), 2),
        }

    salary_taxable = 0.0
    if profile.annual_salary_jpy > 0:
        salary_net = max(0.0, profile.annual_salary_jpy - _salary_deduction_jpy(profile.annual_salary_jpy))
        # Basic deduction (480k) + rough social insurance (~14.5% of salary)
        salary_taxable = max(0.0, salary_net - 480_000.0 - profile.annual_salary_jpy * 0.145)
        with_crypto_taxable = salary_taxable + net_crypto_profit_jpy
    else:
        with_crypto_taxable = max(0.0, net_crypto_profit_jpy - 480_000.0)

    incremental_national = max(
        0.0,
        _national_income_tax(with_crypto_taxable) - _national_income_tax(salary_taxable),
    )
    resident_tax = net_crypto_profit_jpy * 0.10
    if profile.employment_type == "salary" and not national_filing_required:
        # Below ¥200k national threshold, national 所得税 exemption applies for single-employer salary earners,
        # while 10% local resident tax (住民税) still applies.
        est_tax = resident_tax
        note = "Under ¥200k national threshold (salary worker): National 確定申告 exempt, ~10% 住民税 applies."
        advice = (
            f"No national 確定申告 needed for {profile.tax_year}: your company does your job tax (年末調整) and "
            f"net crypto + side income (¥{net_misc:,.0f}) is ≤ ¥200,000. However, report ~¥{est_tax:,.0f} (10% 住民税) "
            f"at your city office during {filing_window} unless already filing 確定申告."
        )
    else:
        est_tax = incremental_national + resident_tax
        note = "Over threshold (or non-salary): Combined National 所得税 + 2.1% surtax + 10% 住民税 estimated."
        sal_txt = f" on ¥{profile.annual_salary_jpy:,.0f} salary" if profile.annual_salary_jpy > 0 else ""
        advice = (
            f"You MUST file 確定申告 for {profile.tax_year} (file between {filing_window}): combined profit "
            f"(¥{net_misc:,.0f}) exceeds the ¥200,000 limit. Set aside ~¥{est_tax:,.0f} total tax reserve{sal_txt}."
        )

    eff_rate = (est_tax / net_crypto_profit_jpy * 100.0) if net_crypto_profit_jpy > 0 else 0.0
    return {
        "estimated_tax_jpy": round(est_tax, 0),
        "effective_rate_pct": round(eff_rate, 1),
        "national_filing_required": national_filing_required,
        "resident_tax_note": note,
        "filing_advice": advice,
        "threshold_pct": round(threshold_pct, 1),
        "remaining_to_threshold_jpy": round(max(0.0, threshold - net_misc), 2),
    }


def fetch_year_trades_bitbank(client: Any, tax_year: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fetch all Bitbank spot & margin fills for `tax_year` (JST calendar year)."""
    if client is None or not getattr(client, "key", None):
        return [], "Bitbank API key not set"

    start_ms = int(datetime(tax_year, 1, 1, 0, 0, 0, tzinfo=JST).timestamp() * 1000)
    end_ms = int(datetime(tax_year, 12, 31, 23, 59, 59, 999000, tzinfo=JST).timestamp() * 1000)

    all_trades: List[Dict[str, Any]] = []
    seen_ids = set()
    cursor_end = end_ms
    err_msg: Optional[str] = None

    for _ in range(30):  # up to 30,000 fills/year cleanly
        try:
            res = client._get(
                "/user/spot/trade_history",
                {"count": "1000", "since": str(start_ms), "end": str(cursor_end), "order": "desc"},
            )
            batch = res.get("trades", []) if isinstance(res, dict) else []
        except Exception as e:
            err_msg = str(e)
            break
        if not batch:
            break
        added = 0
        min_ts = cursor_end
        for t in batch:
            tid = t.get("trade_id")
            ts = int(t.get("executed_at") or 0)
            if ts < min_ts:
                min_ts = ts
            if tid not in seen_ids and start_ms <= ts <= end_ms:
                seen_ids.add(tid)
                all_trades.append(t)
                added += 1
        if len(batch) < 1000 or added == 0 or min_ts <= start_ms:
            break
        cursor_end = min_ts

    all_trades.sort(key=lambda x: int(x.get("executed_at") or 0))
    return all_trades, err_msg


def build_tax_report(
    client: Any,
    profile: TaxProfile,
    fallback_lessons: Optional[List[Dict[str, Any]]] = None,
    cache_path: str = "",
) -> Dict[str, Any]:
    """Compute annual Japan crypto tax summary & trade ledger."""
    trades, fetch_err = fetch_year_trades_bitbank(client, profile.tax_year)
    data_source = "bitbank_trade_history"

    if trades and cache_path:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(trades, f)
        except Exception as e:
            logger.warning(f"Could not save tax cache {cache_path}: {e}")
    elif not trades and cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, list) and cached:
                trades = cached
                data_source = "local_tax_cache"
        except Exception as e:
            logger.warning(f"Could not load tax cache {cache_path}: {e}")

    spot_qty: Dict[str, float] = {}
    spot_avg_cost: Dict[str, float] = {}
    gross_pnl = 0.0
    total_fees = 0.0
    total_interest = 0.0
    ledger_rows: List[Dict[str, Any]] = []
    monthly: Dict[str, Dict[str, float]] = {}

    if trades:
        for t in trades:
            pair = str(t.get("pair") or "")
            side = str(t.get("side") or "")
            pos_side = t.get("position_side")
            amt = float(t.get("amount") or 0.0)
            px = float(t.get("price") or 0.0)
            fee_q = float(t.get("fee_occurred_amount_quote") or t.get("fee_amount_quote") or 0.0)
            interest = float(t.get("interest") or 0.0)
            ts_ms = int(t.get("executed_at") or 0)
            dt_jst = datetime.fromtimestamp(ts_ms / 1000.0, tz=JST)
            ym = dt_jst.strftime("%Y-%m")

            if pos_side:
                # Bitbank's profit_loss on a margin close is already net of the position's entry and exit fees.
                # Adding this fill's fee back here and subtracting it below keeps gross - fees - interest equal
                # to what the account actually gained or lost, instead of taking the fees off twice.
                trade_gross = float(t.get("profit_loss") or 0.0) + fee_q
            else:
                trade_gross = 0.0
                if side == "buy":
                    cur_q = spot_qty.get(pair, 0.0)
                    cur_c = spot_avg_cost.get(pair, 0.0)
                    new_q = cur_q + amt
                    if new_q > 0:
                        spot_avg_cost[pair] = (cur_q * cur_c + amt * px) / new_q
                    spot_qty[pair] = new_q
                elif side == "sell":
                    cur_q = spot_qty.get(pair, 0.0)
                    cur_c = spot_avg_cost.get(pair, 0.0)
                    matched_q = min(amt, cur_q) if cur_q > 0 else 0.0
                    # Only compute gain on quantity matched against known year cost basis; fee subtracted below
                    trade_gross = matched_q * (px - cur_c) if matched_q > 0 else 0.0
                    spot_qty[pair] = max(0.0, cur_q - amt)

            net_row = trade_gross - fee_q - interest
            gross_pnl += trade_gross
            total_fees += fee_q
            total_interest += interest

            m = monthly.setdefault(ym, {"gross_pnl": 0.0, "fees": 0.0, "interest": 0.0, "net_pnl": 0.0, "trades": 0})
            m["gross_pnl"] += trade_gross
            m["fees"] += fee_q
            m["interest"] += interest
            m["net_pnl"] += net_row
            m["trades"] += 1

            ledger_rows.append({
                "trade_id": t.get("trade_id"),
                "time_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "pair": pair,
                "side": f"{side} ({pos_side})" if pos_side else f"{side} (spot)",
                "type": t.get("type", ""),
                "amount": amt,
                "price_jpy": px,
                "gross_pnl_jpy": round(trade_gross, 2),
                "fee_jpy": round(fee_q, 2),
                "interest_jpy": round(interest, 2),
                "net_pnl_jpy": round(net_row, 2),
            })
    else:
        # Graceful offline/mock fallback using local closed trade lessons
        for l in (fallback_lessons or []):
            ts = float(l.get("timestamp") or 0.0)
            dt_jst = datetime.fromtimestamp(ts, tz=JST) if ts > 0 else datetime.now(JST)
            if dt_jst.year != profile.tax_year:
                continue
            pnl = float(l.get("pnl_jpy") or 0.0)
            ym = dt_jst.strftime("%Y-%m")
            gross_pnl += pnl
            m = monthly.setdefault(ym, {"gross_pnl": 0.0, "fees": 0.0, "interest": 0.0, "net_pnl": 0.0, "trades": 0})
            m["gross_pnl"] += pnl
            m["net_pnl"] += pnl
            m["trades"] += 1
            ledger_rows.append({
                "trade_id": f"lesson-{int(ts)}",
                "time_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "pair": l.get("pair", ""),
                "side": l.get("side", ""),
                "type": "closed",
                "amount": 0.0,
                "price_jpy": 0.0,
                "gross_pnl_jpy": round(pnl, 2),
                "fee_jpy": 0.0,
                "interest_jpy": 0.0,
                "net_pnl_jpy": round(pnl, 2),
            })
        data_source = "local_lessons_fallback"

    net_realized = gross_pnl - total_fees - total_interest
    tax_est = estimate_crypto_tax_jpy(net_realized, profile)
    monthly_list = [
        {
            "month": k,
            "trades": int(v["trades"]),
            "gross_pnl_jpy": round(v["gross_pnl"], 2),
            "fees_jpy": round(v["fees"], 2),
            "interest_jpy": round(v["interest"], 2),
            "net_pnl_jpy": round(v["net_pnl"], 2),
        }
        for k, v in sorted(monthly.items())
    ]

    return {
        "tax_year": profile.tax_year,
        "data_source": data_source,
        "fetch_error": fetch_err,
        "profile": asdict(profile),
        "total_trades": len(ledger_rows),
        "gross_realized_pnl_jpy": round(gross_pnl, 2),
        "total_fees_jpy": round(total_fees, 2),
        "total_interest_jpy": round(total_interest, 2),
        "net_realized_profit_jpy": round(net_realized, 2),
        "tax_estimate": tax_est,
        "monthly_breakdown": monthly_list,
        "recent_ledger": list(reversed(ledger_rows[-100:])),
        "all_ledger": ledger_rows,
    }


def render_tax_csv(report: Dict[str, Any]) -> str:
    """Render an Excel-ready UTF-8 BOM CSV for Japan Kakutei Shinkoku (雑所得)."""
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf)
    prof = report.get("profile", {})
    est = report.get("tax_estimate", {})
    w.writerow(["Japan Crypto Tax Report (確定申告 / 雑所得 Reference)", report.get("tax_year")])
    if prof.get("taxpayer_name"):
        w.writerow(["Taxpayer Name", prof.get("taxpayer_name")])
    if prof.get("tax_office"):
        w.writerow(["Tax Office", prof.get("tax_office")])
    w.writerow(["Data Source", report.get("data_source")])
    w.writerow(["Gross Realized PnL (JPY)", report.get("gross_realized_pnl_jpy")])
    w.writerow(["Total Fees/Rebates (JPY, negative = rebate)", report.get("total_fees_jpy")])
    w.writerow(["Total Margin Interest (JPY)", report.get("total_interest_jpy")])
    w.writerow(["Net Taxable Crypto Profit / 雑所得 (JPY)", report.get("net_realized_profit_jpy")])
    w.writerow(["Estimated Tax Reserve (JPY)", est.get("estimated_tax_jpy")])
    w.writerow(["National Filing Required (>200k rule)", est.get("national_filing_required")])
    w.writerow([])
    w.writerow(["Trade ID", "Executed At (JST)", "Pair", "Side", "Type", "Amount", "Price (JPY)", "Gross PnL (JPY)", "Fee/Rebate (JPY)", "Interest (JPY)", "Net PnL (JPY)"])
    for row in report.get("all_ledger", []):
        w.writerow([
            row.get("trade_id"),
            row.get("time_jst"),
            row.get("pair"),
            row.get("side"),
            row.get("type"),
            row.get("amount"),
            row.get("price_jpy"),
            row.get("gross_pnl_jpy"),
            row.get("fee_jpy"),
            row.get("interest_jpy"),
            row.get("net_pnl_jpy"),
        ])
    return buf.getvalue()
