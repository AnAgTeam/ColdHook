"""TOML-конфиг ColdHook: список таргетов (бинарь -> хук) + подпись.

`binary` хранится КАК НАПИСАНО (резолвится вызывающим: для `patch` — относительно
конфига, для `ipa` — относительно корня .app). `sources`/`dylib`/`out` — dev-файлы,
резолвятся абсолютно от каталога конфига.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field


@dataclass
class Signing:
    identity: str = "-"            # codesign identity ("-" = adhoc) или имя серта
    entitlements: str | None = None
    use_ldid: bool = False


@dataclass
class Target:
    name: str
    binary: str                    # путь как написано (relative-to-.app для ipa)
    sources: list[str] = field(default_factory=list)  # исходники хука (абс)
    dylib: str | None = None       # ИЛИ готовый хук-dylib (абс)
    out: str | None = None         # куда писать (patch-режим; абс)
    ldflags: list[str] = field(default_factory=list)  # доп. флаги линковки хука (напр. -lz)
    allow_new_dylibs: bool = False  # разрешить B тянуть dylib, которых нет в таргете


@dataclass
class Config:
    signing: Signing
    targets: list[Target]
    base_dir: str                  # каталог конфига (для разрешения путей)

    def resolve(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.base_dir, p))


def _abs(base: str, p: str | None) -> str | None:
    if p is None:
        return None
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def load(path: str) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    base = os.path.dirname(os.path.abspath(path))

    s = raw.get("signing", {})
    signing = Signing(
        identity=s.get("identity", "-"),
        entitlements=_abs(base, s.get("entitlements")),
        use_ldid=bool(s.get("use_ldid", False)),
    )

    targets: list[Target] = []
    entries = raw.get("target", [])
    if isinstance(entries, dict):  # одиночный [target] вместо [[target]]
        entries = [entries]
    for i, t in enumerate(entries):
        if "binary" not in t:
            raise ValueError(f"target #{i}: нет обязательного поля 'binary'")
        name = t.get("name", os.path.basename(t["binary"]))
        tgt = Target(
            name=name,
            binary=t["binary"],                       # как написано
            sources=[_abs(base, x) for x in t.get("sources", [])],
            dylib=_abs(base, t.get("dylib")),
            out=_abs(base, t.get("out")),
            ldflags=list(t.get("ldflags", [])),
            allow_new_dylibs=bool(t.get("allow_new_dylibs", False)),
        )
        if not tgt.sources and not tgt.dylib:
            raise ValueError(f"target '{name}': нужен 'sources' или 'dylib'")
        if tgt.sources and tgt.dylib:
            raise ValueError(f"target '{name}': укажи либо 'sources', либо 'dylib', не оба")
        targets.append(tgt)

    if not targets:
        raise ValueError("в конфиге нет ни одного [[target]]")

    return Config(signing=signing, targets=targets, base_dir=base)
