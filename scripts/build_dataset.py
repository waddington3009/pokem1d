"""Gera/expande data/pokemon.json a partir da PokéAPI.

Uso:
    python scripts/build_dataset.py                 # Gen 1 (1..151)
    python scripts/build_dataset.py 1 386           # Gens 1-3
    python scripts/build_dataset.py 1 1025 --out data/pokemon.json

Os movesets NÃO são baixados: o bot gera automaticamente um conjunto coerente
com os tipos (ver bot/data/moves.py::default_moveset). Apenas tipos, atributos,
raridade e cadeias de evolução são obtidos.

Requer: aiohttp  (pip install aiohttp)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

try:
    import aiohttp
except ImportError:
    print("Instale aiohttp:  pip install aiohttp")
    sys.exit(1)

API = "https://pokeapi.co/api/v2"
STAT_MAP = {
    "hp": "hp", "attack": "atk", "defense": "def",
    "special-attack": "spa", "special-defense": "spd", "speed": "spe",
}
KNOWN_STONES = {"fire", "water", "thunder", "leaf", "moon", "sun"}


def classify_rarity(base_total: int, capture_rate: int, legendary: bool, mythical: bool) -> str:
    # Baseado na força (base stat total) — distribuição mais natural que capture_rate.
    if mythical:
        return "mythical"
    if legendary:
        return "legendary"
    if base_total >= 600:
        return "superrare"
    if base_total >= 500:
        return "rare"
    if base_total >= 400:
        return "uncommon"
    return "common"


async def fetch_json(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.json()


def parse_stone(item_name: str | None) -> str | None:
    if not item_name:
        return None
    prefix = item_name.split("-")[0]
    return prefix if prefix in KNOWN_STONES else prefix  # mantém o prefixo mesmo se desconhecido


def walk_chain(node: dict, out: dict[str, list[dict]]) -> None:
    """Percorre a cadeia de evolução e registra evoluções diretas por nome."""
    src = node["species"]["name"]
    for nxt in node.get("evolves_to", []):
        details = nxt.get("evolution_details", [{}])
        det = details[0] if details else {}
        trigger = (det.get("trigger") or {}).get("name", "level-up")
        step: dict = {"to_name": nxt["species"]["name"]}
        if det.get("min_level"):
            step["method"] = "level"
            step["level"] = det["min_level"]
        elif trigger == "use-item":
            step["method"] = "stone"
            step["stone"] = parse_stone((det.get("item") or {}).get("name"))
        elif trigger == "trade":
            step["method"] = "level"   # simplificação: trocas viram nível 36
            step["level"] = 36
        elif det.get("min_happiness"):
            step["method"] = "level"
            step["level"] = 30
        else:
            step["method"] = "level"
            step["level"] = 30
        out.setdefault(src, []).append(step)
        walk_chain(nxt, out)


async def build(start: int, end: int, out_path: Path) -> None:
    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(10)
        name_to_id: dict[str, int] = {}
        results: dict[int, dict] = {}
        chains_cache: dict[str, dict[str, list[dict]]] = {}

        async def process(pid: int) -> None:
            async with sem:
                try:
                    poke = await fetch_json(session, f"{API}/pokemon/{pid}")
                    spec = await fetch_json(session, f"{API}/pokemon-species/{pid}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! falhou #{pid}: {exc}")
                    return

                stats = {STAT_MAP[s["stat"]["name"]]: s["base_stat"]
                         for s in poke["stats"] if s["stat"]["name"] in STAT_MAP}
                types = [t["type"]["name"] for t in poke["types"]]
                base_total = sum(stats.values())
                rarity = classify_rarity(
                    base_total, spec.get("capture_rate", 255),
                    spec.get("is_legendary", False), spec.get("is_mythical", False),
                )
                # usa o nome-base da espécie (sem sufixo de forma: 'keldeo' e não
                # 'keldeo-ordinary') — facilita a captura e a resolução de evolução
                species_name = spec["name"]
                name = species_name.replace("-", " ").title()
                name_to_id[species_name] = pid
                entry = {
                    "id": pid,
                    "name": name,
                    "types": types,
                    "base_stats": stats,
                    "rarity": rarity,
                }
                if spec.get("is_legendary"):
                    entry["legendary"] = True
                if spec.get("is_mythical"):
                    entry["mythical"] = True
                    entry["legendary"] = True

                # cadeia de evolução (cacheada por URL)
                chain_url = spec["evolution_chain"]["url"]
                if chain_url not in chains_cache:
                    try:
                        chain_data = await fetch_json(session, chain_url)
                        parsed: dict[str, list[dict]] = {}
                        walk_chain(chain_data["chain"], parsed)
                        chains_cache[chain_url] = parsed
                    except Exception:  # noqa: BLE001
                        chains_cache[chain_url] = {}
                entry["_chain"] = chains_cache[chain_url].get(poke["name"], [])
                results[pid] = entry
                print(f"  ok #{pid:>4} {name} ({rarity})")

        print(f"Baixando espécies {start}..{end} da PokéAPI...")
        await asyncio.gather(*(process(pid) for pid in range(start, end + 1)))

        # resolve nomes de evolução -> ids
        final = []
        for pid in sorted(results):
            entry = results[pid]
            evos = []
            for step in entry.pop("_chain", []):
                to_id = name_to_id.get(step["to_name"])
                if to_id is None:
                    continue
                ev = {"to": to_id, "method": step["method"]}
                if "level" in step:
                    ev["level"] = step["level"]
                if "stone" in step and step["stone"]:
                    ev["stone"] = step["stone"]
                evos.append(ev)
            if evos:
                entry["evolution"] = evos
            final.append(entry)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(final, fh, ensure_ascii=False, indent=2)
        print(f"\n[OK] {len(final)} especies salvas em {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera data/pokemon.json a partir da PokéAPI.")
    parser.add_argument("start", nargs="?", type=int, default=1)
    parser.add_argument("end", nargs="?", type=int, default=151)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "pokemon.json"))
    args = parser.parse_args()
    asyncio.run(build(args.start, args.end, Path(args.out)))


if __name__ == "__main__":
    main()
