#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_report.py — 生成带 v4 自定义布局的 Allure 报告

每次 `allure generate` 都会从模板重写整个报告目录，导致自定义布局（order/stats
左贴、title 独占第二行、params 两行截断、Test body step 点开 JSON）丢失。
本脚本把"生成 + 注入 v4 样式"固化成一步，避免每次手动改。

用法:
  python tools/gen_report.py                      # 自动找最新 allure-results/<ts>，生成并重加样式
  python tools/gen_report.py --src 20260814_104008  # 指定批次
  python tools/gen_report.py --serve              # 生成后后台起 http.server 0.0.0.0:8090
  python tools/gen_report.py --port 9000 --serve  # 自定义端口
  python tools/gen_report.py --patch-only --src 20260814_104008  # 只注入样式（不重新 generate），供 main.py 调用
"""
import os
import sys
import shutil
import subprocess
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLURE_RESULTS = os.path.join(BASE_DIR, "allure-results")
REPORT_HTML = os.path.join(BASE_DIR, "report", "html")
TEMPLATE_CSS = os.path.join(BASE_DIR, "tools", "report_template", "styles.css")
ALLURE_CLI = os.path.join(BASE_DIR, "allure", "bin", "allure")

# 注入到 index.html 的自定义 IIFE（列表页短名 + Test body step 点开 JSON）。
# 写在 tools/report_template 之外的逻辑，这里内联避免额外文件依赖。
INJECT_JS = r"""(function(){
  if (window.__customReportPatchV5) return;
  window.__customReportPatchV5 = true;

  function formatPyDict(s){
    if (s == null) return '';
    var t = String(s);
    if (/\n/.test(t)) return t;
    var out = '', depth = 0, inStr = false, strCh = '';
    for (var i=0;i<t.length;i++){
      var c = t[i], prev = i>0?t[i-1]:'';
      if (inStr){
        out += c;
        if (c === strCh && prev !== '\\') inStr = false;
        continue;
      }
      if (c === "'" || c === '"'){
        inStr = true; strCh = c; out += c; continue;
      }
      if (c === '{' || c === '[' || c === '('){ out += c; depth++; out += '\n' + '  '.repeat(Math.max(depth-1,0)); continue; }
      if (c === '}' || c === ']' || c === ')'){ depth--; out += '\n' + '  '.repeat(Math.max(depth,0)) + c; continue; }
      if (c === ',' && depth>0){ out += c + '\n' + '  '.repeat(depth); continue; }
      out += c;
    }
    return out;
  }

  function getShortName(raw){
    if (!raw) return '';
    var t = String(raw);
    var m = t.match(/'description'\s*:\s*'([^']{0,80})'/);
    if (m) return m[1];
    var i = t.indexOf('{');
    return i >= 0 ? t.slice(0, i).replace(/^[\s,]+|[\s,]+$/g,'') : t;
  }

  function decorateOne(leaf){
    if (!leaf || leaf.__patched) return;
    leaf.__patched = true;

    // Test body step descriptions: replace raw text with a clean short name;
    // click ▶ to expand the formatted JSON. The Behaviors list keeps its
    // original 2-line CSS clamp (no short-name injection into .node__title —
    // that previously leaked into the order row).
    var steps = leaf.querySelectorAll('.step__name, .step__title');
    steps.forEach(function(s){
      var rawText = s.textContent || '';
      if (!/\{|\[/.test(rawText)) return;
      if (s.__stepPatched) return;
      s.__stepPatched = true;
      var shortName = getShortName(rawText);
      if (shortName && shortName !== rawText) {
        s.textContent = shortName;
        s.setAttribute('title', rawText);
      }
      s.classList.add('has-json');
      var pre = document.createElement('pre');
      pre.className = 'step__json';
      pre.textContent = formatPyDict(rawText);
      s.parentNode && s.parentNode.insertBefore(pre, s.nextSibling);
      s.addEventListener('click', function(){
        var exp = s.classList.toggle('expanded');
        if (exp) pre.classList.add('show'); else pre.classList.remove('show');
      });
    });
  }

  function scan(){ document.querySelectorAll('.node__leaf').forEach(decorateOne); }
  function schedule(){ clearTimeout(window.__t); window.__t = setTimeout(scan, 50); }

  scan();
  var mo = new MutationObserver(schedule);
  mo.observe(document.body, { childList: true, subtree: true });
})();"""


def bpath(p):
    """转成 git-bash 友好的正斜杠路径（Windows 反斜杠在 bash 里会被当转义）。"""
    return p.replace("\\", "/")


def find_latest_results():
    entries = [d for d in os.listdir(ALLURE_RESULTS)
               if os.path.isdir(os.path.join(ALLURE_RESULTS, d))]
    if entries:
        latest = max(entries, key=lambda d: os.path.getmtime(os.path.join(ALLURE_RESULTS, d)))
        return os.path.join(ALLURE_RESULTS, latest), latest
    return ALLURE_RESULTS, "latest"


def generate(src, dst):
    cmd = 'bash "%s" generate "%s" -o "%s" --clean' % (
        bpath(ALLURE_CLI), bpath(src), bpath(dst))
    print("  $ " + cmd)
    # allure 在 Windows 退出码可能为 -1073740791（fast-fail / STATUS_STACK_BUFFER_OVERRUN），
    # 但报告确实已生成；以 index.html 是否存在为准，不检查 returncode。
    subprocess.run(cmd, shell=True)
    return os.path.exists(os.path.join(dst, "index.html"))


def patch_styles(dst):
    if os.path.exists(TEMPLATE_CSS):
        shutil.copy(TEMPLATE_CSS, os.path.join(dst, "styles.css"))
        print("  patched styles.css (v4 layout)")
    else:
        print("  WARN: template styles.css missing, skipped")


def patch_index(dst):
    index = os.path.join(dst, "index.html")
    if not os.path.exists(index):
        return
    with open(index, encoding="utf-8") as f:
        html = f.read()
    if "customReportPatchV5" in html:
        print("  index.html already patched, skipped")
        return
    needle = '<script src="plugin/screen-diff/index.js"></script>'
    marker = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-FVWC4GKEYS"></script>'
    if needle in html and marker in html:
        block = needle + "\n    <script>\n" + INJECT_JS + "\n    </script>\n    " + marker
        html = html.replace(needle + "\n    " + marker, block, 1)
        with open(index, "w", encoding="utf-8") as f:
            f.write(html)
        print("  injected custom IIFE into index.html")
    else:
        print("  WARN: insertion point not found in index.html, skipped")


def serve(dst, port):
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0",
         "--directory", dst],
        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
    )
    print("  serving at http://127.0.0.1:%d (and your public IP)" % port)
    print("  server PID %d" % proc.pid)


def main():
    parser = argparse.ArgumentParser(description="Generate Allure report with v4 custom layout")
    parser.add_argument("--src", help="allure-results subdir name (default: latest)")
    parser.add_argument("--serve", action="store_true", help="start http.server after generate")
    parser.add_argument("--port", type=int, default=8090, help="serve port (default 8090)")
    parser.add_argument("--patch-only", action="store_true",
                        help="only inject v4 styles/index patch into an EXISTING report dir (no allure generate). "
                             "Used by main.py which already ran `allure generate`.")
    args = parser.parse_args()

    if args.src:
        src = os.path.join(ALLURE_RESULTS, args.src)
        ts = args.src
    else:
        src, ts = find_latest_results()

    if not os.path.exists(src):
        print("ERROR: results not found: %s" % src)
        sys.exit(1)

    dst = os.path.join(REPORT_HTML, ts)
    print("Generating report: %s -> %s" % (bpath(src), bpath(dst)))
    if args.patch_only:
        if not os.path.exists(os.path.join(dst, "index.html")):
            print("ERROR: report dir not generated yet (missing index.html): %s" % bpath(dst))
            sys.exit(1)
        print("  --patch-only: skip allure generate, inject styles/index into existing dir")
    else:
        generate(src, dst)
    patch_styles(dst)
    patch_index(dst)
    print("Report ready: %s" % bpath(dst))
    if args.serve:
        serve(dst, args.port)


if __name__ == "__main__":
    main()
