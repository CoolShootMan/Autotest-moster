#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
"""
Filename         : Pear_FE_BE_performance.py
Description      : Simulate N concurrent real browser users accessing a target URL,
                   collect FE (Navigation Timing, Paint) and BE (API response time)
                   metrics, and generate a Markdown performance report.
Usage            :
    python3 Pear_FE_BE_performance.py
    python3 Pear_FE_BE_performance.py --url "https://example.com" --concurrent 20
    python3 Pear_FE_BE_performance.py --url "https://example.com" --concurrent 5 --headful
Time             : 2026/07/22
Author           : Marvis File Agent
Version          : 1.0
Dependencies     : playwright (playwright install chromium required)
"""

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Configurable defaults ──────────────────────────────────────────────
DEFAULT_URL = (
    "https://pear.us/lindazhou300/post/"
    "test-axs-la-office-integrations-arena-event-1-2"
)
DEFAULT_CONCURRENT = 10


# ── Helper: flatten dict ───────────────────────────────────────────────
def _flatten(d: dict, parent_key: str = "", sep: str = "_") -> dict:
    items: list = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


# ── Single-user session ────────────────────────────────────────────────
def _run_single_user(
    url: str,
    user_id: int,
    headless: bool = True,
    duration_seconds: float = 0,
) -> Dict[str, Any]:
    """
    Launch a browser instance and repeatedly navigate to *url* for
    *duration_seconds* (or a single round if <= 0).  Each round collects
    FE metrics (Navigation / Paint Timing) + BE API response times.
    """
    from playwright.sync_api import sync_playwright

    global_start = time.time()
    iterations: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        # ── Browser launch (once) ──────────────────────────────────────
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception as launch_err:
            err_msg = str(launch_err)
            if "Executable doesn't exist" in err_msg:
                import subprocess, sys
                print(f"  [AUTO-FIX] Installing Chromium...")
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True, timeout=300,
                )
                browser = p.chromium.launch(headless=headless)
            else:
                raise

        # ── Iteration loop ─────────────────────────────────────────────
        while True:
            elapsed = time.time() - global_start
            if duration_seconds > 0 and elapsed >= duration_seconds:
                break
            if duration_seconds <= 0 and iterations:
                break  # single-shot mode: stop after one iteration

            iter_result: Dict[str, Any] = {
                "success": False,
                "error": None,
                "navigation_timing": {},
                "paint_timing": {},
                "api_requests": [],
                "iter_duration_ms": 0,
            }
            iter_start = time.time()

            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()

                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=60000)

                # Simulate reading: scroll slowly
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
                time.sleep(1.5)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.7)")
                time.sleep(1.5)

                # Wait for LCP to finalize
                page.wait_for_timeout(2000)

                # --- LCP: Promise-based PerformanceObserver ---
                lcp_ms = page.evaluate(
                    """() => {
                        return new Promise((resolve) => {
                            let resolved = false;
                            const po = new PerformanceObserver((list) => {
                                const entries = list.getEntries();
                                if (entries.length > 0 && !resolved) {
                                    resolved = true;
                                    const last = entries[entries.length - 1];
                                    resolve(Math.round(last.renderTime || last.startTime));
                                    po.disconnect();
                                }
                            });
                            po.observe({ type: 'largest-contentful-paint', buffered: true });
                            setTimeout(() => {
                                if (!resolved) { po.disconnect(); resolve(null); }
                            }, 5000);
                        });
                    }"""
                )

                # --- BE: Resource Timing ---
                api_requests: List[Dict[str, Any]] = []
                resource_entries = page.evaluate(
                    """() => {
                        return performance.getEntriesByType('resource').map(r => ({
                            name: r.name,
                            initiatorType: r.initiatorType,
                            duration: Math.round(r.duration),
                            startTime: Math.round(r.startTime),
                            responseEnd: Math.round(r.responseEnd),
                            transferSize: r.transferSize || 0,
                            dns: Math.round(r.domainLookupEnd - r.domainLookupStart) || 0,
                            tcp: Math.round(r.connectEnd - r.connectStart) || 0,
                            ttfb: Math.round(r.responseStart - r.requestStart) || 0,
                        }));
                    }"""
                )
                for entry in resource_entries:
                    api_requests.append({
                        "url": entry["name"],
                        "resource_type": entry["initiatorType"],
                        "status": 0,
                        "method": "",
                        "duration_ms": entry["duration"],
                        "start_time_ms": entry["startTime"],
                        "transfer_size_bytes": entry["transferSize"],
                        "dns_ms": entry["dns"],
                        "tcp_ms": entry["tcp"],
                        "ttfb_ms": entry["ttfb"],
                    })

                # --- FE: Navigation Timing ---
                nav_timing_raw = page.evaluate(
                    """() => {
                        const t = performance.getEntriesByType('navigation')[0];
                        if (!t) return null;
                        return {
                            dns: t.domainLookupEnd - t.domainLookupStart,
                            tcp: t.connectEnd - t.connectStart,
                            ttfb: t.responseStart - t.requestStart,
                            dom_interactive: t.domInteractive - t.requestStart,
                            dom_complete: t.domComplete - t.requestStart,
                            load_event: t.loadEventEnd - t.loadEventStart,
                            total: t.loadEventEnd - t.fetchStart,
                        };
                    }"""
                )

                # --- FE: Paint Timing ---
                paint_timing_raw = page.evaluate(
                    """() => {
                        const paints = {};
                        performance.getEntriesByType('paint').forEach(e => {
                            paints[e.name] = Math.round(e.startTime);
                        });
                        const nav = performance.getEntriesByType('navigation')[0];
                        const fcp = nav ? Math.round(nav.fcp) : undefined;
                        return { ...paints, fcp };
                    }"""
                )

                if lcp_ms is not None:
                    paint_timing_raw["lcp"] = lcp_ms

                iter_result["success"] = True
                iter_result["navigation_timing"] = nav_timing_raw or {}
                iter_result["paint_timing"] = paint_timing_raw or {}
                iter_result["api_requests"] = api_requests

                context.close()

            except Exception as exc:
                iter_result["error"] = str(exc)

            iter_result["iter_duration_ms"] = round((time.time() - iter_start) * 1000)
            iterations.append(iter_result)

        browser.close()

    total_ms = round((time.time() - global_start) * 1000)
    success_count = sum(1 for it in iterations if it["success"])
    fail_count = len(iterations) - success_count

    return {
        "user_id": user_id,
        "total_duration_ms": total_ms,
        "total_iterations": len(iterations),
        "success_iterations": success_count,
        "fail_iterations": fail_count,
        "iterations": iterations,
    }


# ── Aggregation helpers ────────────────────────────────────────────────
def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f) if c != f else sorted_vals[f]


def _summarize_fe(user_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = [
        "dns", "tcp", "ttfb", "dom_interactive",
        "dom_complete", "load_event", "total",
    ]
    summary: Dict[str, Any] = {}
    for m in metrics:
        vals = [
            r["navigation_timing"].get(m, 0)
            for r in user_results
            if r["success"] and r["navigation_timing"]
        ]
        vals = [v for v in vals if v is not None]
        if vals:
            summary[m] = {
                "count": len(vals),
                "avg": round(statistics.mean(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "p50": round(_percentile(vals, 50), 2),
                "p95": round(_percentile(vals, 95), 2),
                "p99": round(_percentile(vals, 99), 2),
            }

    # Paint metrics
    paint_keys = ["first-paint", "first-contentful-paint", "fcp", "lcp"]
    paint_summary: Dict[str, Any] = {}
    for pk in paint_keys:
        vals = [
            r["paint_timing"].get(pk, 0)
            for r in user_results
            if r["success"] and r["paint_timing"]
        ]
        vals = [v for v in vals if v is not None and v > 0]
        if vals:
            paint_summary[pk] = {
                "count": len(vals),
                "avg": round(statistics.mean(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "p50": round(_percentile(vals, 50), 2),
                "p95": round(_percentile(vals, 95), 2),
                "p99": round(_percentile(vals, 99), 2),
            }
    summary["paint"] = paint_summary
    return summary


# API request filter: only count fetch/xhr, not static assets
_API_INITIATORS = {"fetch", "xmlhttprequest", "other"}

def _summarize_be(user_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group API requests by URL and compute aggregate timing.
    Only includes fetch/xhr requests; excludes static assets (script/img/css/link)."""
    api_map: Dict[str, List[float]] = {}
    for r in user_results:
        if not r["success"]:
            continue
        for req in r["api_requests"]:
            init_type = req.get("resource_type", "")
            # Skip static assets
            if init_type in ("script", "img", "css", "link", "iframe", "media", "font"):
                continue
            url = req["url"]
            dur = req.get("duration_ms", 0)
            if dur > 0:
                api_map.setdefault(url, []).append(dur)

    be_summary: Dict[str, Any] = {}
    for url, durs in api_map.items():
        be_summary[url] = {
            "count": len(durs),
            "avg": round(statistics.mean(durs), 2),
            "min": round(min(durs), 2),
            "max": round(max(durs), 2),
            "p50": round(_percentile(durs, 50), 2),
            "p95": round(_percentile(durs, 95), 2),
            "p99": round(_percentile(durs, 99), 2),
        }
    return be_summary


# ── Baseline threshold (ms) ────────────────────────────────────────────
BASELINE_MS = 3000

# ── Report generation ──────────────────────────────────────────────────
def _generate_report(
    url: str,
    concurrent: int,
    headless: bool,
    total_duration_s: float,
    test_duration_min: float,
    user_results: List[Dict[str, Any]],
    fe_summary: Dict[str, Any],
    be_summary: Dict[str, Any],
    output_dir: Path,
) -> Path:
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    filename = f"FE_BE_performance_report_{ts}.html"
    output_path = output_dir / filename

    total_iters = sum(r.get("total_iterations", 0) for r in user_results)
    success_iters = sum(r.get("success_iterations", 0) for r in user_results)
    fail_iters = total_iters - success_iters

    nav_metrics = ["dns", "tcp", "ttfb", "dom_interactive", "dom_complete", "load_event", "total"]
    nav_labels = {
        "dns": "DNS Lookup",
        "tcp": "TCP Connect",
        "ttfb": "TTFB",
        "dom_interactive": "DOM Interactive",
        "dom_complete": "DOM Complete",
        "load_event": "Load Event",
        "total": "Total Page Load",
    }
    paint_data = fe_summary.get("paint", {})
    paint_labels = {
        "first-paint": "First Paint",
        "first-contentful-paint": "First Contentful Paint",
        "fcp": "FCP (Navigation API)",
        "lcp": "LCP (Largest Contentful Paint)",
    }
    sorted_be = sorted(be_summary.items(), key=lambda x: x[1]["avg"], reverse=True) if be_summary else []

    # ── Conclusion data (compute upfront for UX badge) ──
    all_fe: List[Dict[str, Any]] = []
    for m in nav_metrics:
        if m in fe_summary:
            all_fe.append({"label": nav_labels.get(m, m), **fe_summary[m]})
    for pk, d in paint_data.items():
        all_fe.append({"label": paint_labels.get(pk, pk), **d})

    be_fail_count = 0
    if be_summary:
        for d in be_summary.values():
            if d["avg"] > BASELINE_MS:
                be_fail_count += 1

    fe_fail = [m for m in all_fe if m["avg"] > BASELINE_MS]
    fe_pass = [m for m in all_fe if m["avg"] <= BASELINE_MS]
    failing_count = len(fe_fail) + be_fail_count

    # ── UX badge ──
    if failing_count == 0:
        ux_badge = ("Excellent", "#22c55e", "#166534",
                     "All metrics within the 3s baseline. Pages load responsively and API responses are consistently fast, providing a smooth user experience.")
    elif failing_count <= 2:
        ux_badge = ("Acceptable", "#f59e0b", "#92400e",
                     "Most metrics meet the 3s baseline with a few exceptions. Users may experience occasional delays but overall experience remains usable.")
    elif failing_count <= 5:
        ux_badge = ("Degraded", "#f97316", "#9a3412",
                     "Several key metrics exceed the 3s threshold. Users are likely to perceive noticeable slowness during page loads and interactions. Recommend investigation into the slowest endpoints.")
    else:
        ux_badge = ("Poor", "#ef4444", "#991b1b",
                     "A significant number of metrics fail the 3s baseline. Page load and API response times are substantially above acceptable thresholds, resulting in a frustrating user experience. Immediate performance optimization is strongly advised.")

    # ── Helper: table row with baseline coloring ──
    def _td_cls(val: float) -> str:
        return ' class="fail"' if val > BASELINE_MS else ""

    def _status_cell(avg_val: float) -> str:
        if avg_val > BASELINE_MS:
            return '<td class="status-fail">FAIL (&gt;3s)</td>'
        return '<td class="status-pass">PASS</td>'

    # ── Build HTML ──
    h: List[str] = []
    h.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FE &amp; BE Performance Report</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #1e293b; padding: 40px 24px; }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 28px; margin-bottom: 20px; color: #0f172a; }
  h2 { font-size: 20px; margin: 36px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #e2e8f0; color: #334155; }
  .meta { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px 24px; margin-bottom: 28px; font-size: 14px; background: #fff; border-radius: 8px; padding: 18px 22px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  .meta-item { display: flex; }
  .meta-key { color: #64748b; min-width: 180px; }
  .meta-val { font-weight: 600; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 28px; font-size: 13px; }
  th { background: #f1f5f9; text-align: left; padding: 10px 12px; font-weight: 600; color: #475569; white-space: nowrap; }
  td { padding: 8px 12px; border-top: 1px solid #f1f5f9; }
  tr:hover td { background: #f8fafc; }
  td.fail { color: #dc2626; font-weight: 700; }
  td.status-pass { color: #16a34a; font-weight: 700; }
  td.status-fail { color: #dc2626; font-weight: 700; background: #fef2f2; }
  td.status-ok { color: #16a34a; font-weight: 600; }
  td.status-err { color: #dc2626; font-weight: 600; background: #fef2f2; }
  .ux-badge { display: inline-block; padding: 6px 16px; border-radius: 20px; font-weight: 700; font-size: 14px; }
  .conclusion-box { background: #fff; border-radius: 8px; padding: 22px; box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 28px; }
  .conclusion-box p { margin: 6px 0; font-size: 14px; }
  .violation-list { list-style: none; padding: 0; }
  .violation-list li { padding: 6px 0; border-bottom: 1px solid #f1f5f9; font-size: 13px; }
  .violation-list li:last-child { border-bottom: none; }
  .violation-list code { background: #f1f5f9; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
  .api-url { font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace; font-size: 12px; word-break: break-all; max-width: 360px; display: inline-block; }
  footer { text-align: center; color: #94a3b8; font-size: 12px; margin-top: 40px; }
</style>
</head>
<body>
<div class="container">
""")

    h.append(f"<h1>FE &amp; BE Performance Report</h1>")
    h.append('<div class="meta">')
    meta_items = [
        ("Generated", now.strftime("%Y-%m-%d %H:%M:%S")),
        ("Target URL", f'<a href="{url}" style="word-break:break-all">{url}</a>'),
        ("Concurrent Users", str(concurrent)),
        ("Headless Mode", str(headless)),
        ("Test Duration", f"{test_duration_min:.0f} min" if test_duration_min > 0 else "single shot"),
        ("Wall-clock Duration", f"{total_duration_s:.1f}s"),
        ("Total Iterations", f"{total_iters} ({success_iters} OK, {fail_iters} failed)"),
    ]
    for k, v in meta_items:
        h.append(f'<div class="meta-item"><span class="meta-key">{k}</span><span class="meta-val">{v}</span></div>')
    h.append("</div>")

    # ── 1. FE Navigation Timing ──
    h.append("<h2>1. FE — Navigation Timing (ms)</h2>")
    h.append("<table><thead><tr><th>Metric</th><th>Count</th><th>Avg</th><th>Min</th><th>Max</th><th>p50</th><th>p95</th><th>p99</th><th>Status</th></tr></thead><tbody>")
    for m in nav_metrics:
        if m in fe_summary:
            d = fe_summary[m]
            h.append(
                f"<tr><td>{nav_labels.get(m, m)}</td><td>{d['count']}</td>"
                f"<td{_td_cls(d['avg'])}>{d['avg']}</td>"
                f"<td{_td_cls(d['min'])}>{d['min']}</td>"
                f"<td{_td_cls(d['max'])}>{d['max']}</td>"
                f"<td{_td_cls(d['p50'])}>{d['p50']}</td>"
                f"<td{_td_cls(d['p95'])}>{d['p95']}</td>"
                f"<td{_td_cls(d['p99'])}>{d['p99']}</td>"
                f"{_status_cell(d['avg'])}</tr>"
            )
    h.append("</tbody></table>")

    # ── 2. FE Paint Timing ──
    if paint_data:
        h.append("<h2>2. FE — Paint Timing (ms)</h2>")
        h.append("<table><thead><tr><th>Metric</th><th>Count</th><th>Avg</th><th>Min</th><th>Max</th><th>p50</th><th>p95</th><th>p99</th><th>Status</th></tr></thead><tbody>")
        for pk, d in paint_data.items():
            h.append(
                f"<tr><td>{paint_labels.get(pk, pk)}</td><td>{d['count']}</td>"
                f"<td{_td_cls(d['avg'])}>{d['avg']}</td>"
                f"<td{_td_cls(d['min'])}>{d['min']}</td>"
                f"<td{_td_cls(d['max'])}>{d['max']}</td>"
                f"<td{_td_cls(d['p50'])}>{d['p50']}</td>"
                f"<td{_td_cls(d['p95'])}>{d['p95']}</td>"
                f"<td{_td_cls(d['p99'])}>{d['p99']}</td>"
                f"{_status_cell(d['avg'])}</tr>"
            )
        h.append("</tbody></table>")

    # ── 3. BE API Response Time ──
    h.append("<h2>3. BE — API Response Time (ms)</h2>")
    if be_summary:
        h.append("<table><thead><tr><th>API URL</th><th>Count</th><th>Avg</th><th>Min</th><th>Max</th><th>p50</th><th>p95</th><th>p99</th><th>Status</th></tr></thead><tbody>")
        for api_url, d in sorted_be:
            display_url = api_url if len(api_url) <= 120 else api_url[:117] + "..."
            h.append(
                f"<tr><td><span class=\"api-url\" title=\"{api_url}\">{display_url}</span></td><td>{d['count']}</td>"
                f"<td{_td_cls(d['avg'])}>{d['avg']}</td>"
                f"<td{_td_cls(d['min'])}>{d['min']}</td>"
                f"<td{_td_cls(d['max'])}>{d['max']}</td>"
                f"<td{_td_cls(d['p50'])}>{d['p50']}</td>"
                f"<td{_td_cls(d['p95'])}>{d['p95']}</td>"
                f"<td{_td_cls(d['p99'])}>{d['p99']}</td>"
                f"{_status_cell(d['avg'])}</tr>"
            )
        h.append("</tbody></table>")
    else:
        h.append("<p style=\"color:#94a3b8;font-style:italic\">(No API requests captured)</p>")

    # ── 4. Per-user Summary ──
    h.append("<h2>4. Per-User Summary</h2>")
    h.append("<table><thead><tr><th>User ID</th><th>Iterations</th><th>OK / Fail</th><th>Total Duration (s)</th><th>Error</th></tr></thead><tbody>")
    for r in user_results:
        total_iters_u = r.get("total_iterations", 0)
        ok_u = r.get("success_iterations", 0)
        fail_u = r.get("fail_iterations", 0)
        status_cls = "status-ok" if fail_u == 0 else "status-err"
        err = r.get("error", "") or ""
        if err and len(err) > 60:
            err = err[:57] + "..."
        h.append(
            f"<tr><td>{r['user_id']}</td>"
            f"<td>{total_iters_u}</td>"
            f"<td class=\"{status_cls}\">{ok_u} / {fail_u}</td>"
            f"<td>{r.get('total_duration_ms', 0) / 1000:.1f}</td>"
            f"<td style=\"color:#dc2626;font-size:12px\">{err}</td></tr>"
        )
    h.append("</tbody></table>")

    # ── 5. Performance Conclusion ──
    h.append("<h2>5. Performance Conclusion &amp; User Experience</h2>")
    h.append('<div class="conclusion-box">')
    h.append(f"<p><strong>Baseline:</strong> {BASELINE_MS}ms (3 seconds)</p>")
    h.append(f"<p><strong>FE Metrics Passed:</strong> {len(fe_pass)} / {len(all_fe)}</p>")
    h.append(f"<p><strong>BE API Endpoints Failed:</strong> {be_fail_count} / {len(be_summary) if be_summary else 0}</p>")
    h.append("</div>")

    if fe_fail:
        h.append("<h3>FE Violations (avg &gt; 3s)</h3>")
        h.append('<ul class="violation-list">')
        for m in fe_fail:
            h.append(
                f"<li><strong style=\"color:#dc2626\">{m['label']}</strong>: "
                f"avg <code>{m['avg']}ms</code>, p95 <code>{m['p95']}ms</code>, p99 <code>{m['p99']}ms</code></li>"
            )
        h.append("</ul>")

    if be_fail_count:
        h.append("<h3>BE API Violations (avg &gt; 3s)</h3>")
        h.append('<ul class="violation-list">')
        for api_url, d in sorted_be:
            if d["avg"] > BASELINE_MS:
                display_url = api_url if len(api_url) <= 120 else api_url[:117] + "..."
                h.append(
                    f"<li><strong style=\"color:#dc2626\"><span class=\"api-url\">{display_url}</span></strong>: "
                    f"avg <code>{d['avg']}ms</code>, p95 <code>{d['p95']}ms</code>, p99 <code>{d['p99']}ms</code></li>"
                )
        h.append("</ul>")

    ux_label, ux_bg, ux_fg, ux_desc = ux_badge
    h.append("<h3>Overall User Experience Assessment</h3>")
    h.append(f'<p><span class="ux-badge" style="background:{ux_bg};color:{ux_fg}">{ux_label}</span></p>')
    h.append(f"<p style=\"margin-top:10px;line-height:1.6\">{ux_desc}</p>")

    # ── Footer ──
    h.append("<footer>Report generated by Pear_FE_BE_performance.py</footer>")
    h.append("</div></body></html>")

    output_path.write_text("\n".join(h), encoding="utf-8")
    return output_path


# ── Main entrypoint ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Concurrent browser-based FE & BE performance test."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Target URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=DEFAULT_CONCURRENT,
        help=f"Number of concurrent users (default: {DEFAULT_CONCURRENT})",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Test duration in minutes. 0 = single shot (default: 0).",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browsers in headed (visible) mode instead of headless.",
    )
    args = parser.parse_args()

    url = args.url
    concurrent = args.concurrent
    headless = not args.headful
    duration_seconds = args.duration * 60.0

    # Resolve output directory: script_dir/../output/
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Target URL      : {url}")
    print(f"Concurrent users: {concurrent}")
    print(f"Duration        : {'%.0f min' % args.duration if args.duration > 0 else 'single shot'}")
    print(f"Headless        : {headless}")
    print(f"Output dir      : {output_dir}")
    print(f"{'─' * 60}")

    overall_start = time.time()

    # Launch concurrent user sessions
    user_results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrent) as executor:
        futures = {
            executor.submit(_run_single_user, url, i + 1, headless, duration_seconds): i + 1
            for i in range(concurrent)
        }
        for future in as_completed(futures):
            user_id = futures[future]
            try:
                res = future.result()
                user_results.append(res)
                ok = res["success_iterations"]
                fail = res["fail_iterations"]
                status = f"OK ({ok}/{ok+fail})" if fail == 0 else f"FAIL ({fail} errs)"
            except Exception as exc:
                user_results.append({
                    "user_id": user_id,
                    "total_duration_ms": 0,
                    "total_iterations": 0,
                    "success_iterations": 0,
                    "fail_iterations": 1,
                    "iterations": [],
                    "error": str(exc),
                })
                status = "CRASH"
            total_s = res.get("total_duration_ms", 0) / 1000
            iters = res.get("total_iterations", 0)
            print(f"  User {user_id:>3d}  [{status}]  {iters} iters / {total_s:.1f}s")

    overall_end = time.time()
    total_duration_s = overall_end - overall_start

    # Flatten all iterations from all users
    all_iterations: List[Dict[str, Any]] = []
    for ur in user_results:
        all_iterations.extend(ur.get("iterations", []))

    total_iters = len(all_iterations)
    success_iters = sum(1 for it in all_iterations if it["success"])
    print(f"\nTotal iterations collected: {total_iters} ({success_iters} OK, {total_iters - success_iters} failed)")

    # Summarize
    fe_summary = _summarize_fe(all_iterations)
    be_summary = _summarize_be(all_iterations)

    # Generate report
    report_path = _generate_report(
        url=url,
        concurrent=concurrent,
        headless=headless,
        total_duration_s=total_duration_s,
        test_duration_min=args.duration,
        user_results=user_results,
        fe_summary=fe_summary,
        be_summary=be_summary,
        output_dir=output_dir,
    )

    print(f"\n{'─' * 60}")
    print(f"Total elapsed: {total_duration_s:.1f} s")
    print(f"Report saved  : {report_path}")

    # ── Auto-serve: ensure HTTP server is running on output_dir for LAN access ──
    serve_port = 9999
    lan_ip = _get_lan_ip()
    _ensure_http_server(output_dir, serve_port)

    if lan_ip:
        print(f"LAN access    : http://{lan_ip}:{serve_port}/{report_path.name}")
    else:
        print(f"Local access  : http://localhost:{serve_port}/{report_path.name}")

    return 0


# ── Helpers for LAN serving ────────────────────────────────────────────
def _get_lan_ip() -> str:
    """Return the primary LAN IPv4 address, or empty string."""
    try:
        # macOS: check en0 first, fallback to any active interface
        result = subprocess.run(
            ["ifconfig"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
            if m:
                ip = m.group(1)
                if not ip.startswith("127."):
                    return ip
    except Exception:
        pass
    return ""


def _ensure_http_server(directory: Path, port: int) -> None:
    """Start a Python HTTP server in *directory* on *port* if not already running."""
    # Check if port is already in use
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    in_use = sock.connect_ex(("127.0.0.1", port)) == 0
    sock.close()
    if in_use:
        return  # server already running

    def _serve():
        import http.server
        os.chdir(str(directory))
        handler = http.server.SimpleHTTPRequestHandler
        with http.server.HTTPServer(("0.0.0.0", port), handler) as httpd:
            httpd.serve_forever()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    time.sleep(0.3)  # give the socket a moment to bind


if __name__ == "__main__":
    sys.exit(main())
