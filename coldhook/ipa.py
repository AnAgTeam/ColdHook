"""Patching bundle: .ipa (iOS) или .app-каталога (macOS) — merge хука в бинари in-place.

Структура патча одинакова для обеих платформ: распаковать -> найти .app -> по каждому
таргету (путь относительно .app) merge in-place -> запаковать. Подпись по умолчанию НЕ
делается (это забота пользователя; iOS-установка потребует её отдельно).
"""
from __future__ import annotations

import glob
import json
import os
from .diagnostics import traced
import pathlib
import shutil
import subprocess
import tempfile
import zipfile

from . import build, console
from .build import PatchError
from .config import Config

try:
    import lief
except (ImportError, OSError):  # pragma: no cover - dependency is declared in pyproject.toml
    lief = None


def _shared_hook_descriptions(dylib: str) -> list[str]:
    """Read shared selector metadata from the dylib's exported symbols."""
    if lief is not None:
        try:
            parsed = lief.MachO.parse(dylib)
            images = [parsed] if hasattr(parsed, "exported_symbols") else list(parsed)
            result = []
            for image in images:
                for symbol in image.exported_symbols:
                    name = symbol.name
                    if not name.startswith("_COLDHOOK_DYN_"):
                        continue
                    fields = name[len("_COLDHOOK_DYN_"):].split("__CH__")
                    if len(fields) == 3:
                        kind_selector = fields[0].split("_", 1)
                        if len(kind_selector) == 2 and kind_selector[1]:
                            result.append(f"{kind_selector[1]}:{fields[1]}")
            return list(dict.fromkeys(result))
        except Exception:
            # Keep the macOS command-line fallback for old/partial installs.
            pass
    try:
        p = subprocess.run(["nm", "-a", dylib], capture_output=True, text=True)
    except OSError:
        return []
    result = []
    marker = "_COLDHOOK_DYN_"
    for line in p.stdout.splitlines():
        if marker not in line:
            continue
        name = line[line.index(marker) + len(marker):].split()[0]
        fields = name.split("__CH__")
        if len(fields) >= 3:
            kind_selector = fields[0].split("_", 1)
            if len(kind_selector) == 2:
                result.append(f"{kind_selector[1]}:{fields[1]}")
    return list(dict.fromkeys(result))


def _shared_hook_selectors(dylib: str) -> set[str]:
    return {item.split(":", 1)[0] for item in _shared_hook_descriptions(dylib)
            if ":" in item}


def _validate_shared_selectors(app: str, dylib: str) -> None:
    """Reject a selector that resolves to more than one Mach-O image.

    A basename is convenient for normal bundles, but becomes ambiguous when
    two embedded frameworks contain equally named binaries.  In that case the
    macro may use a bundle-relative path (or an absolute path) instead.
    """
    selectors = _shared_hook_selectors(dylib)
    if not selectors:
        return
    images: list[str] = []
    seen_real: set[str] = set()
    for root, _, files in os.walk(app):
        for name in files:
            path = os.path.join(root, name)
            if not build.macho.is_macho(path):
                continue
            real = os.path.realpath(path)
            if real in seen_real:
                continue
            seen_real.add(real)
            images.append(path)
    for selector in selectors:
        matches = []
        for path in images:
            rel = os.path.relpath(path, app)
            base = os.path.basename(path)
            if selector.startswith("/"):
                hit = os.path.abspath(path) == os.path.abspath(selector)
            elif "/" in selector:
                hit = rel == selector or rel.endswith("/" + selector)
            else:
                hit = selector == base
            if hit:
                matches.append(rel)
        if len(matches) > 1:
            raise PatchError(
                "shared: ambiguous binary selector "
                f"{selector!r}; matches: {', '.join(matches)}. "
                "Specify a bundle-relative or absolute path in the macro.")


def _merge_shared_thin(target: str, dylib: str, out: str,
                       import_path: str | None,
                       target_path: str | None = None) -> dict[str, object]:
    report_path = out + ".report.json"
    if os.path.exists(report_path):
        os.remove(report_path)
    try:
        build.toolchain.merge(target, dylib, out, mode="shared",
                              import_path=import_path, report_json=report_path,
                              target_path=target_path)
        try:
            with open(report_path, encoding="utf-8") as report_file:
                report = json.load(report_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise PatchError(f"MachOMerger did not produce a valid JSON report: {exc}") from exc
    finally:
        if os.path.exists(report_path):
            os.remove(report_path)
    if (not isinstance(report, dict) or report.get("version") != 1
            or report.get("status") not in {"patched", "no-applicable-hooks"}
            or not isinstance(report.get("hooks"), list)):
        raise PatchError("MachOMerger returned an unsupported JSON report")
    hooks = report["hooks"]
    if ((report["status"] == "patched") != bool(hooks)
            or any(not isinstance(hook, dict)
                   or not all(isinstance(hook.get(field), str)
                              for field in ("kind", "selector", "locator", "handler"))
                   for hook in hooks)):
        raise PatchError("MachOMerger returned an invalid hook JSON report")
    return report


@traced('Patching shared binary', 'target')
def _merge_shared(target: str, dylib: str, out: str,
                  import_path: str | None) -> dict[str, object]:
    """Merge a shared hook into a thin image or every compatible FAT slice."""
    info = build.macho.inspect(target)
    if not info.is_fat:
        return _merge_shared_thin(target, dylib, out, import_path)
    hook_info = build.macho.inspect(dylib)
    patchable = [a for a in info.archs
                 if a in build.macho.MERGER_ARCHS and a in hook_info.archs]
    if not patchable:
        raise PatchError(f"shared FAT {info.archs}: no supported slice in common with hook {hook_info.archs}")
    with tempfile.TemporaryDirectory(prefix="coldhook_shared_fat_") as tmp:
        replacements: dict[str, str] = {}
        hooks: list[dict[str, object]] = []
        seen_hooks: set[tuple[object, ...]] = set()
        for arch in patchable:
            thin_target = os.path.join(tmp, f"target_{arch}")
            thin_hook = dylib if not hook_info.is_fat else os.path.join(tmp, f"hook_{arch}")
            build.macho.thin(target, arch, thin_target)
            if hook_info.is_fat:
                build.macho.thin(dylib, arch, thin_hook)
            patched = os.path.join(tmp, f"patched_{arch}")
            report = _merge_shared_thin(thin_target, thin_hook, patched,
                                        import_path, target_path=target)
            for hook in report["hooks"]:
                if not isinstance(hook, dict):
                    raise PatchError("MachOMerger returned an invalid hook record")
                key = tuple(hook.get(field) for field in
                            ("kind", "selector", "locator", "handler"))
                if key not in seen_hooks:
                    seen_hooks.add(key)
                    hooks.append(hook)
            replacements[arch] = patched
        build.macho.replace_slices(target, replacements, out)
        return {"version": 1,
                "status": "patched" if hooks else "no-applicable-hooks",
                "target": target,
                "hooks": hooks}


def _run(cmd: list[str], what: str, cwd: str | None = None) -> None:
    build.toolchain._run(cmd, what, cwd=cwd)


@traced('Unpacking IPA', 'path')
def _unpack_ipa(path: str, destination: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(destination)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PatchError(f"Unpacking failed: {exc}") from exc


@traced('Packing IPA', 'output')
def _pack_ipa(stage: str, output: str) -> None:
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            payload = os.path.join(stage, "Payload")
            for root, _, files in os.walk(payload):
                for name in files:
                    path = os.path.join(root, name)
                    archive.write(path, os.path.relpath(path, stage))
    except OSError as exc:
        raise PatchError(f"Packing failed: {exc}") from exc


@traced('Finding application', 'root')
def _find_app(root: str) -> str:
    """Найти .app: для IPA — Payload/*.app; если root сам .app — он и есть."""
    if root.endswith(".app") and os.path.isdir(root):
        return root
    cands = glob.glob(os.path.join(root, "Payload", "*.app"))
    if not cands:
        cands = glob.glob(os.path.join(root, "*.app"))
    if not cands:
        raise PatchError(f"No .app found inside {root}")
    return cands[0]


@traced('Patching bundle', 'inp', 'out')
def patch_bundle(inp: str, config: Config, out: str, do_sign: bool = False) -> str:
    build.toolchain.ensure_merger()
    is_ipa = inp.lower().endswith(".ipa") or os.path.isfile(inp)
    work = tempfile.mkdtemp(prefix="coldhook_bundle_")
    try:
        if is_ipa:
            console.stage(f"Unpacking IPA: {os.path.basename(inp)}")
            _unpack_ipa(inp, work)
            stage = work
        else:
            # .app-каталог: работаем на копии, чтобы не трогать оригинал
            console.stage(f"Copying .app: {os.path.basename(inp)}")
            dst = os.path.join(work, os.path.basename(inp))
            shutil.copytree(inp, dst, symlinks=True)
            stage = dst

        app = _find_app(stage)
        console.stage(f"Application: {os.path.relpath(app, work)}")

        for t in config.targets:
            binary = os.path.join(app, t.binary)
            # merge in-place внутри бандла; подпись по флагу (по умолч. off)
            build.patch_target(t, config.signing, binary, binary, do_sign=do_sign)

        # запаковка
        if is_ipa:
            console.stage(f"Packing IPA: {os.path.basename(out)}")
            out_abs = os.path.abspath(out)
            if os.path.exists(out_abs):
                os.remove(out_abs)
            # zip из каталога staging, сохраняя Payload/ и права/симлинки
            _pack_ipa(stage, out_abs)
        else:
            console.stage(f"Saving .app: {out}")
            if os.path.exists(out):
                shutil.rmtree(out)
            shutil.copytree(app, out, symlinks=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    console.success(f"Bundle patched -> {out}")
    return out


@traced('Patching shared bundle', 'inp', 'out')
def patch_shared_bundle(inp: str, dylib: str, out: str, do_sign: bool = False,
                        import_path: str | None = None, runtime: str | None = None,
                        verbose: bool = False, skip_unsupported: bool = False) -> str:
    """Apply one shared hook dylib to every Mach-O in an app bundle.

    File discovery is deliberately dumb: every regular file is probed, and the
    merger decides whether the current image has applicable declarations.
    """
    build.toolchain.ensure_merger()
    if not os.path.exists(dylib):
        raise PatchError(f"Shared hook dylib not found: {dylib}")
    if runtime is None:
        candidate = os.path.join(os.path.dirname(os.path.abspath(dylib)), "libcoldhook.dylib")
        if os.path.exists(candidate):
            runtime = candidate
    if not runtime or not os.path.exists(runtime):
        raise PatchError("Shared runtime not found; specify --runtime <path-to-libcoldhook.dylib>")
    work = tempfile.mkdtemp(prefix="coldhook_shared_bundle_")
    is_ipa = inp.lower().endswith(".ipa") or os.path.isfile(inp)
    try:
        if is_ipa:
            console.stage(f"Unpacking IPA: {os.path.basename(inp)}")
            _unpack_ipa(inp, work)
            stage = work
        else:
            if not inp.endswith(".app") or not os.path.isdir(inp):
                raise PatchError("shared: expected an .app directory or .ipa file")
            stage = os.path.join(work, os.path.basename(inp))
            shutil.copytree(inp, stage, symlinks=True)
        app = _find_app(stage)
        _validate_shared_selectors(app, dylib)
        hook_descriptions = _shared_hook_descriptions(dylib) if verbose else []
        if verbose:
            console.stage(f"Declared hooks: {len(hook_descriptions)}")
            for description in hook_descriptions:
                console.detail(description)
        # Shared sideload bundles carry the hook runtime with the app.  The
        # merger rewrites LC_LOAD_DYLIB to @executable_path/Frameworks/<name>.
        bundled_dylib = None
        if import_path is None:
            frameworks = os.path.join(app, "Frameworks")
            os.makedirs(frameworks, exist_ok=True)
            bundled_dylib = os.path.join(frameworks, os.path.basename(dylib))
            shutil.copy2(dylib, bundled_dylib)
        runtime_dest = os.path.join(app, "Frameworks", os.path.basename(runtime))
        os.makedirs(os.path.dirname(runtime_dest), exist_ok=True)
        shutil.copy2(runtime, runtime_dest)
        dylib_real = os.path.realpath(dylib)
        targets: list[str] = []
        seen_targets: set[str] = set()
        for root, _, files in os.walk(stage):
            for name in files:
                target = os.path.join(root, name)
                # Test bundles and dSYM payloads are not application images;
                # build-for-testing places FAT test artifacts next to the app.
                path_parts = pathlib.Path(target).parts
                framework_name = next((p for p in reversed(path_parts) if p.endswith(".framework")), "")
                is_xctest_support = (
                    name.startswith(("libXCTest", "XCTest", "XCT"))
                    or framework_name.startswith(("XCTest", "XC", "XCT", "Testing"))
                    or "XCUnit.framework" in target
                )
                if (".xctest" in target or ".dSYM" in target or "PlugIns" in path_parts
                        or is_xctest_support):
                    continue
                target_real = os.path.realpath(target)
                if target_real in seen_targets:
                    continue
                seen_targets.add(target_real)
                if (os.path.realpath(target) == dylib_real
                        or (bundled_dylib and os.path.realpath(target) == os.path.realpath(bundled_dylib))
                        or os.path.realpath(target) == os.path.realpath(runtime_dest)):
                    continue
                if not build.macho.is_macho(target):
                    continue
                targets.append(target)

        console.stage(f"Processing Mach-O: found {len(targets)}")
        processed = 0
        patched = 0
        unchanged = 0
        skipped = 0
        applied_hooks = 0
        for index, target in enumerate(targets, 1):
            rel = os.path.relpath(target, app)
            console.progress(index, len(targets), rel)
            merged = target + ".coldhook"
            try:
                report = _merge_shared(target, dylib, merged, import_path)
            except Exception as exc:
                if os.path.exists(merged):
                    os.remove(merged)
                if skip_unsupported and any(marker in str(exc) for marker in
                                            ("FatNotMachO", "Unsupported", "not a Mach-O",
                                             "Unhandled command Unknown")):
                    skipped += 1
                    if verbose:
                        console.detail(f"skipped as unsupported: {exc}")
                    continue
                raise
            hooks = report["hooks"]
            if not isinstance(hooks, list):
                raise PatchError("MachOMerger returned an invalid hook list")
            changed = report["status"] == "patched"
            shutil.copymode(target, merged)
            shutil.move(merged, target)
            if do_sign:
                build.toolchain.sign(target)
            processed += 1
            if changed:
                patched += 1
                applied_hooks += len(hooks)
                console.applied(f"Hooks applied: {len(hooks)}")
            else:
                unchanged += 1
                console.not_applied("No applicable hooks")
            if verbose:
                for hook in hooks:
                    if not isinstance(hook, dict):
                        raise PatchError("MachOMerger returned an invalid hook record")
                    kind = str(hook.get("kind", "?")).upper()
                    locator = str(hook.get("locator", "?"))
                    if kind == "ADDRESS" and locator.startswith("COLDHOOK_ADDR_"):
                        locator = locator[len("COLDHOOK_ADDR_"):]
                    handler = str(hook.get("handler", "?"))
                    console.detail(f"{kind:<7} {locator} → {handler}")
        if is_ipa:
            console.stage(f"Packing IPA: {os.path.basename(out)}")
            out_abs = os.path.abspath(out)
            if os.path.exists(out_abs):
                os.remove(out_abs)
            _pack_ipa(stage, out_abs)
        else:
            if os.path.exists(out):
                shutil.rmtree(out)
            shutil.copytree(stage, out, symlinks=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    summary = (f"Done: found {len(targets)}, processed {processed}, "
               f"patched {patched}, hooks {applied_hooks}, "
               f"unchanged {unchanged}")
    if skipped:
        summary += f", skipped {skipped}"
    console.success(summary)
    console.detail(f"Output: {out}")
    return out
