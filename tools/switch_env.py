#!/usr/bin/env python3
"""
Environment switch script — one-command replacement of URL prefixes in YAML/Python files

Usage:
    python tools/switch_env.py --to=staging   # Switch to development environment
    python tools/switch_env.py --to=release   # Switch to test environment
    python tools/switch_env.py --to=prod       # Switch to production environment
    python tools/switch_env.py --dry-run=staging  # Preview mode (no file changes)
    python tools/switch_env.py --list          # List all environments
"""

import argparse
import os
import re
import shutil
import sys
import glob
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "env_config.yaml"


def load_config():
    """Load environment configuration"""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg):
    """Save environment configuration"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_target_files(scan_patterns):
    """Get list of files to scan (excludes example files and __pycache__)"""
    files = []
    for pattern in scan_patterns:
        full_pattern = BASE_DIR / pattern
        for path in glob.glob(str(full_pattern), recursive=True):
            # Exclude example files and pycache
            if "__pycache__" in path or "example" in path.lower():
                continue
            files.append(Path(path))
    return sorted(set(files))


def replace_content(text, old_base, new_base, old_env, new_env):
    """
    Replace URL prefixes and cookie filenames in text.
    Replacements:
      1. URL: https://release.pear.us → https://staging.pear.us
      2. Cookie filenames: cookie_release.json → cookie_staging.json etc.
    """
    # 1. Replace URL prefix
    url_pattern = re.escape(old_base) + r"(?=/|\?|#|$)"
    text = re.sub(url_pattern, new_base, text)

    # 2. Replace cookie filenames (uniform _{env}.json suffix)
    # Match filename references of the form "cookie_<old_env>"
    cookie_patterns = [
        # Standard naming: cookie_release.json → cookie_staging.json
        (re.escape(f"cookie_{old_env}.json"), f"cookie_{new_env}.json"),
        # co_seller: cookie_release_co_seller.json → cookie_staging_co_seller.json
        (re.escape(f"cookie_{old_env}_co_seller.json"), f"cookie_{new_env}_co_seller.json"),
        # partner_coseller variants
        (re.escape(f"cookie_partner_coseller_{old_env}.json"), f"cookie_partner_coseller_{new_env}.json"),
        (re.escape(f"cookie_partner_{old_env}.json"), f"cookie_partner_{new_env}.json"),
        (re.escape(f"cookie_{old_env}_partner_coseller.json"), f"cookie_{new_env}_partner_coseller.json"),
        (re.escape(f"cookie_{old_env}_partner.json"), f"cookie_{new_env}_partner.json"),
        # Legacy patterns
        (re.escape(f"cookie_release_co_seller.json"), f"cookie_{new_env}_co_seller.json"),
        (re.escape(f"cookie_partner_coseller_release.json"), f"cookie_partner_coseller_{new_env}.json"),
    ]
    for old_pattern, new_replacement in cookie_patterns:
        text = re.sub(old_pattern, new_replacement, text)

    return text


def process_file(filepath, old_base, new_base, old_env, new_env, dry_run=False, verbose=False):
    """Process a single file, return number of replacements made"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"  [SKIP] {filepath} - read failed: {e}")
        return 0

    new_content = replace_content(content, old_base, new_base, old_env, new_env)

    if new_content == content:
        return 0  # No changes

    url_count = len(re.findall(re.escape(old_base) + r"(?=/|\?|#|$)", content))
    cookie_count = 0
    cookie_patterns = [
        (re.escape(f"cookie_{old_env}.json"), f"cookie_{new_env}.json"),
        (re.escape(f"cookie_{old_env}_co_seller.json"), f"cookie_{new_env}_co_seller.json"),
        (re.escape(f"cookie_partner_coseller_{old_env}.json"), f"cookie_partner_coseller_{new_env}.json"),
        (re.escape(f"cookie_partner_{old_env}.json"), f"cookie_partner_{new_env}.json"),
        (re.escape(f"cookie_{old_env}_partner_coseller.json"), f"cookie_{new_env}_partner_coseller.json"),
        (re.escape(f"cookie_{old_env}_partner.json"), f"cookie_{new_env}_partner.json"),
        (re.escape("cookie_release_co_seller.json"), f"cookie_{new_env}_co_seller.json"),
        (re.escape("cookie_partner_coseller_release.json"), f"cookie_partner_coseller_{new_env}.json"),
    ]
    for old_pattern, _ in cookie_patterns:
        cookie_count += len(re.findall(old_pattern, content))
    total_count = url_count + cookie_count

    if dry_run:
        print(f"  [DRY] {filepath}  →  would replace {total_count} occurrences (URL:{url_count} + cookie:{cookie_count})")
        if verbose:
            lines = content.split("\n")
            new_lines = new_content.split("\n")
            for i, (old_l, new_l) in enumerate(zip(lines, new_lines)):
                if old_l != new_l:
                    print(f"       line {i+1}: {old_l.strip()[:80]}")
                    print(f"       →     {new_l.strip()[:80]}")
    else:
        # Create backup
        backup_path = filepath.with_suffix(filepath.suffix + ".bak")
        shutil.copy2(filepath, backup_path)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  [MODIFIED] {filepath}  ({total_count} occurrences: URL×{url_count} cookie×{cookie_count})  |  backup: {backup_path.name}")

    return total_count


def preview_change(content, old_base, new_base):
    """Preview diff after replacement (simple string diff)"""
    new_content = replace_content(content, old_base, new_base)
    if new_content == content:
        return None
    return new_content


def switch_env(target_env, dry_run=False, verbose=False):
    """Execute environment switch"""
    cfg = load_config()
    envs = cfg.get("envs", {})

    if target_env not in envs:
        print(f"[ERROR] Unknown environment: {target_env}")
        print("Available environments:", list(envs.keys()))
        return False

    current_env = cfg.get("current_env", "release")
    if target_env == current_env and not dry_run:
        print(f"[INFO] Already on {target_env} ({envs[target_env]['desc']}), no switch needed.")
        return True

    old_base = envs[current_env]["base"]
    new_base = envs[target_env]["base"]

    print(f"\n{'='*60}")
    print(f"Switching:  {current_env} ({old_base})")
    print(f"       →   {target_env} ({new_base})")
    print(f"Mode:      {'DRY-RUN (preview, no file changes)' if dry_run else 'Execute'}")
    print(f"{'='*60}\n")

    scan_patterns = cfg.get("scan_patterns", [])
    files = get_target_files(scan_patterns)
    print(f"Files to scan: {len(files)}\n")

    total_replacements = 0
    for filepath in files:
        count = process_file(filepath, old_base, new_base, current_env, target_env,
                              dry_run=dry_run, verbose=verbose)
        total_replacements += count

    print(f"\n{'='*60}")
    if dry_run:
        print(f"DRY-RUN COMPLETE: {total_replacements} occurrences would be replaced")
        print("Run without --dry-run to apply the changes.")
    else:
        print(f"Switch complete: {total_replacements} occurrences replaced")
        print(f"Backup files (*.bak) are in their respective directories and can be deleted manually.")
        # Update current environment
        cfg["current_env"] = target_env
        save_config(cfg)
        print(f"\n[OK] config/env_config.yaml updated, current_env = {target_env}")
    print(f"{'='*60}\n")
    return True


def list_envs(cfg):
    """List all available environments and mark the current one"""
    envs = cfg.get("envs", {})
    current_env = cfg.get("current_env", "release")
    print(f"{'='*60}")
    print("Available environments:")
    for name, info in envs.items():
        if not isinstance(info, dict):
            print(f"  {name:<10}")
            continue
        marker = "  (current)" if name == current_env else ""
        desc = info.get("desc", "")
        base = info.get("base", "")
        print(f"  {name:<10}{desc}{marker}")
        if base:
            print(f"             base: {base}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="One-command test environment URL switcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/switch_env.py --to=staging    # Switch to development environment
  python tools/switch_env.py --to=prod         # Switch to production environment
  python tools/switch_env.py --dry-run=release # Preview switch to test environment (no file changes)
  python tools/switch_env.py --list            # List all environments
  python tools/switch_env.py --to=staging -v   # Show detailed replacement lines
        """
    )
    parser.add_argument("--to", dest="target", help="Target environment (staging / release / prod)")
    parser.add_argument("--dry-run", dest="dry_run", help="Preview mode, value is target environment")
    parser.add_argument("--list", action="store_true", help="List all available environments")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed replacement lines")

    args = parser.parse_args()

    # Priority: --dry-run > --to > --list
    if args.dry_run:
        success = switch_env(args.dry_run, dry_run=True, verbose=args.verbose)
    elif args.target:
        success = switch_env(args.target, dry_run=False, verbose=args.verbose)
    elif args.list:
        cfg = load_config()
        list_envs(cfg)
        success = True
    else:
        parser.print_help()
        print()
        cfg = load_config()
        list_envs(cfg)
        success = True

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
