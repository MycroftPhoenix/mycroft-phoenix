"""
Construction d'un « code-map » structuré dans LadybugDB.

Parse les modules Python cibles (AST) et peuples un graphe LadybugDB
(real_ladybug, API compatible Kuzu) avec :

  (Module {name, path, doc, category, is_skill,
           n_classes, n_functions, n_consts, n_imports})
      -[:IMPORTS]->  (Import {name, source, asname, imported})
      -[:EXPOSES]->  (Symbol {id, module, name, kind, lineno, doc})
                       -[:HAS_PARAM]-> (Param {id, symbol_id, name, annotation, has_default, default_value})

  (Import)-[:RESOLVES_TO]->(Module)   # pour les imports internes au projet

  - ``category`` : emplacement (2e segment du nom de module, ex. 'tts',
    'stt', 'skills', 'lora', 'windows', 'core'...).
  - ``is_skill`` : True si le module définit une classe finissant par 'Skill'
    (détection AST, sans import du code).
  - ``doc`` : 1re ligne de la docstring du module = courte description.

Cela permet de retrouver instantanément, pour chaque module : son emplacement,
sa description, s'il s'agit d'une skill, ce qu'il importe, ce qu'il expose
(classes/fonctions/constantes) et les paramètres de chacun, sans reparser.

Usage CLI::

    python tools/build_module_map.py \
        --scan mycroft mycroft_lora_win \
        --db data/graph/module_map.lbdb

Requêtes exemple (Cypher via l'adapter LadybugStorageAdapter.conn)::

    # tous les modules, classés par emplacement
    MATCH (m:Module) RETURN m.category, m.name, m.doc ORDER BY m.category, m.name;
    # modules d'une catégorie (ex. tts)
    MATCH (m:Module {category:'tts'}) RETURN m.name, m.doc, m.is_skill;
    # uniquement les skills
    MATCH (m:Module) WHERE m.is_skill = True RETURN m.name, m.path ORDER BY m.name;
    # imports / symbols / params d'un module
    MATCH (m:Module {name:'mycroft.capabilities'})-[:IMPORTS]->(i:Import)
        RETURN i.name, i.source, i.imported;
    MATCH (m:Module {name:'mycroft.capabilities'})-[:EXPOSES]->(s:Symbol)
        RETURN s.name, s.kind, s.lineno ORDER BY s.lineno;
    MATCH (s:Symbol {id:'mycroft.capabilities::build_tts'})-[:HAS_PARAM]->(p:Param)
        RETURN p.name, p.annotation, p.has_default, p.default_value;
"""

import argparse
import ast
import sys
from pathlib import Path

try:
    import real_ladybug as _ladybug
except ImportError:  # pragma: no cover
    _ladybug = None

STDLIB = set(getattr(sys, "stdlib_module_names", set()))

# Bases de skills Mycroft (détection par nom de classe)
SKILL_SUFFIX = "Skill"

SCHEMA = [
    "CREATE NODE TABLE Module(name STRING, path STRING, doc STRING, "
    "category STRING, is_skill BOOLEAN, "
    "n_classes INT64, n_functions INT64, n_consts INT64, n_imports INT64, "
    "PRIMARY KEY (name))",
    "CREATE NODE TABLE Symbol(id STRING, module STRING, name STRING, "
    "kind STRING, lineno INT64, doc STRING, PRIMARY KEY (id))",
    "CREATE NODE TABLE Param(id STRING, symbol_id STRING, name STRING, "
    "annotation STRING, has_default BOOLEAN, default_value STRING, "
    "PRIMARY KEY (id))",
    "CREATE NODE TABLE Import(name STRING, source STRING, asname STRING, "
    "imported STRING, PRIMARY KEY (name))",
    "CREATE REL TABLE EXPOSES (FROM Module TO Symbol)",
    "CREATE REL TABLE HAS_PARAM (FROM Symbol TO Param)",
    "CREATE REL TABLE IMPORTS (FROM Module TO Import)",
    "CREATE REL TABLE RESOLVES_TO (FROM Import TO Module)",
]

EDGES_FIRST = [
    "DROP TABLE IF EXISTS EXPOSES",
    "DROP TABLE IF EXISTS HAS_PARAM",
    "DROP TABLE IF EXISTS IMPORTS",
    "DROP TABLE IF EXISTS RESOLVES_TO",
]
NODES = [
    "DROP TABLE IF EXISTS Module",
    "DROP TABLE IF EXISTS Symbol",
    "DROP TABLE IF EXISTS Param",
    "DROP TABLE IF EXISTS Import",
]


# ── AST helpers ─────────────────────────────────────────────────────────────

def _path_to_module(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _ann(node) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _func_params(func) -> list:
    """Retourne [(name, annotation, has_default, default_value), ...]."""
    out = []
    a = func.args
    pos = list(a.posonlyargs) + list(a.args)
    defaults = list(a.defaults)
    n_pos = len(pos)
    n_def = len(defaults)
    for i, arg in enumerate(pos):
        has_default = n_def > 0 and i >= n_pos - n_def
        default = _ann(defaults[i - (n_pos - n_def)]) if has_default else ""
        out.append((arg.arg, _ann(arg.annotation), has_default, default))
    if a.vararg:
        out.append(("*" + a.vararg.arg, _ann(a.vararg.annotation), False, ""))
    kw_defaults = list(a.kw_defaults)
    for i, kw in enumerate(a.kwonlyargs):
        dflt = kw_defaults[i] if i < len(kw_defaults) else None
        has_default = dflt is not None
        out.append((kw.arg, _ann(kw.annotation), has_default,
                    _ann(dflt) if has_default else ""))
    if a.kwarg:
        out.append(("**" + a.kwarg.arg, _ann(a.kwarg.annotation), False, ""))
    return out


def _classify(root_name: str, scanned_roots: set) -> str:
    if root_name in scanned_roots:
        return "internal"
    if root_name in STDLIB:
        return "stdlib"
    return "thirdparty"


def scan_file(path: Path, module_name: str) -> dict:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        print(f"  [skip] {path}: SyntaxError {exc}")
        return None

    imports = []          # (name, asname, imported, source)
    symbols = []          # (name, kind, lineno, doc, params)
    n_classes = n_functions = n_consts = 0
    is_skill = False

    module_doc = ast.get_docstring(tree) or ""
    if module_doc:
        module_doc = module_doc.strip().splitlines()[0][:200]

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                imports.append((alias.name, alias.asname or "", "", root))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".")[0] if mod else ""
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "")
                              for a in node.names)
            imports.append((mod, "", names, root))
        elif isinstance(node, ast.ClassDef):
            n_classes += 1
            bases_str = [_ann(b) for b in node.bases]
            base_names = [s.split(".")[-1] for s in bases_str]
            if any(bn.endswith(SKILL_SUFFIX) for bn in base_names):
                is_skill = True
            params = [("bases", "", False, ", ".join(bases_str))]
            symbols.append((node.name, "class", node.lineno,
                            (ast.get_docstring(node) or "").strip().splitlines()[0][:200]
                            if ast.get_docstring(node) else "",
                            params))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n_functions += 1
            doc = ast.get_docstring(node)
            symbols.append((node.name, "function", node.lineno,
                            doc.strip().splitlines()[0][:200] if doc else "",
                            _func_params(node)))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and not tgt.id.startswith("__"):
                    n_consts += 1
                    symbols.append((tgt.id, "const", node.lineno, "", []))

    # repli description : 1re docstring de classe/fonction si module sans doc
    if not module_doc:
        for sym in symbols:
            if sym[3]:
                module_doc = sym[3]
                break

    # catégorie = emplacement (2e segment du nom de module)
    parts = module_name.split(".")
    if module_name == "mycroft" or (len(parts) == 1 and parts[0] == "mycroft"):
        category = "core"
    elif parts and parts[0] == "mycroft_lora_win":
        category = "windows"
    elif len(parts) >= 2 and parts[0] == "mycroft":
        category = parts[1]
    else:
        category = parts[0] if parts else "core"

    return {
        "name": module_name,
        "path": str(path),
        "doc": module_doc,
        "category": category,
        "is_skill": is_skill,
        "imports": imports,
        "symbols": symbols,
        "n_classes": n_classes,
        "n_functions": n_functions,
        "n_consts": n_consts,
    }


# ── DB writer ───────────────────────────────────────────────────────────────

class ModuleMapBuilder:
    def __init__(self, db_path: str):
        if _ladybug is None:
            raise ImportError("real_ladybug n'est pas installé")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = _ladybug.Database(str(self.db_path), read_only=False)
        self.conn = _ladybug.Connection(self.db)

    def _exec(self, query: str, params: dict = None):
        try:
            self.conn.execute(query, parameters=params or {})
        except Exception as exc:  # CREATE idempotent / contraintes
            if "already exists" in str(exc).lower():
                return
            # relance pour diagnostic sur les INSERT
            raise

    def init_schema(self, rebuild: bool = False):
        if rebuild:
            for stmt in EDGES_FIRST + NODES:
                try:
                    self.conn.execute(stmt)
                except Exception:
                    pass
        for stmt in SCHEMA:
            self._exec(stmt)

    def add_module(self, mod: dict, scanned_roots: set):
        self._exec(
            "MERGE (m:Module {name:$name}) "
            "SET m.path=$path, m.doc=$doc, m.category=$cat, m.is_skill=$isk, "
            "m.n_classes=$nc, m.n_functions=$nf, m.n_consts=$nk, m.n_imports=$ni",
            {"name": mod["name"], "path": mod["path"], "doc": mod["doc"],
             "cat": mod["category"], "isk": bool(mod["is_skill"]),
             "nc": mod["n_classes"], "nf": mod["n_functions"],
             "nk": mod["n_consts"], "ni": len(mod["imports"])},
        )
        # imports
        for name, asname, imported, root in mod["imports"]:
            source = _classify(root, scanned_roots)
            self._exec(
                "MERGE (i:Import {name:$name}) "
                "SET i.source=$source, i.asname=$asname, i.imported=$imported",
                {"name": name, "source": source, "asname": asname or "",
                 "imported": imported or ""},
            )
            self._exec(
                "MATCH (m:Module {name:$m}) MATCH (i:Import {name:$i}) "
                "MERGE (m)-[:IMPORTS]->(i)",
                {"m": mod["name"], "i": name},
            )
        # symbols + params
        for sname, kind, lineno, doc, params in mod["symbols"]:
            sid = f"{mod['name']}::{sname}"
            self._exec(
                "MERGE (s:Symbol {id:$id}) "
                "SET s.module=$module, s.name=$name, s.kind=$kind, "
                "s.lineno=$lineno, s.doc=$doc",
                {"id": sid, "module": mod["name"], "name": sname,
                 "kind": kind, "lineno": lineno, "doc": doc or ""},
            )
            self._exec(
                "MATCH (m:Module {name:$m}) MATCH (s:Symbol {id:$id}) "
                "MERGE (m)-[:EXPOSES]->(s)",
                {"m": mod["name"], "id": sid},
            )
            for pname, ann, has_default, default in params:
                pid = f"{sid}::{pname}"
                self._exec(
                    "MERGE (p:Param {id:$id}) "
                    "SET p.symbol_id=$sid, p.name=$name, p.annotation=$ann, "
                    "p.has_default=$hd, p.default_value=$dv",
                    {"id": pid, "sid": sid, "name": pname, "ann": ann,
                     "hd": bool(has_default), "dv": default or ""},
                )
                self._exec(
                    "MATCH (s:Symbol {id:$sid}) MATCH (p:Param {id:$pid}) "
                    "MERGE (s)-[:HAS_PARAM]->(p)",
                    {"sid": sid, "pid": pid},
                )

    def finalize(self):
        """Passe finale : relie les imports internes aux Modules cibles.

        Faite après tous les inserts pour capturer les références « en avant »
        (A importe B alors que B n'était pas encore inséré)."""
        self._exec(
            "MATCH (i:Import {source:'internal'}) "
            "MATCH (m:Module {name:i.name}) "
            "MERGE (i)-[:RESOLVES_TO]->(m)"
        )

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass


# ── Orchestration ──────────────────────────────────────────────────────────

def build(scan_dirs, db_path: str, rebuild: bool = False):
    roots = [Path(d) for d in scan_dirs]
    files = []
    for r in roots:
        files += [p for p in r.rglob("*.py") if p.is_file()]
    files = sorted(set(files))

    # racine repo = plus long ancêtre commun aux dossiers scannés
    common = None
    for r in roots:
        parts = r.parts
        if common is None:
            common = parts
        else:
            common = tuple(a for a, b in zip(common, parts) if a == b)
    repo_root = Path(*common) if common else Path(".")

    # noms de modules scannés (pour détecter les imports internes)
    scanned_roots = set()
    parsed = []
    for f in files:
        mname = _path_to_module(f, repo_root)
        scanned_roots.add(mname.split(".")[0])
        mod = scan_file(f, mname)
        if mod:
            parsed.append(mod)

    builder = ModuleMapBuilder(db_path)
    builder.init_schema(rebuild=rebuild)
    for mod in parsed:
        builder.add_module(mod, scanned_roots)
    builder.finalize()
    builder.close()

    print(f"Code-map construite : {len(parsed)} modules -> {db_path}")
    return len(parsed)


# ── Lecture / interrogation ─────────────────────────────────────────────────

def _open_ro(db_path):
    db = _ladybug.Database(str(db_path), read_only=True)
    conn = _ladybug.Connection(db)
    return db, conn


def run_query(db_path: str, cypher: str, as_json: bool = False):
    db, conn = _open_ro(db_path)
    try:
        rows = conn.execute(cypher).get_all()
    finally:
        conn.close()
        db.close()
    if as_json:
        import json
        print(json.dumps(rows, ensure_ascii=False, default=str))
    else:
        for r in rows:
            print(r)


def show_categories(db_path: str):
    run_query(db_path,
              "MATCH (m:Module) RETURN m.category, COUNT(*) AS n ORDER BY m.category")


def show_skills(db_path: str):
    run_query(db_path,
              "MATCH (m:Module) WHERE m.is_skill = True "
              "RETURN m.name, m.path ORDER BY m.name")


def show_module(db_path: str, name: str):
    db, conn = _open_ro(db_path)
    try:
        info = conn.execute(
            "MATCH (m:Module {name:$n}) RETURN m.name, m.category, "
            "m.is_skill, m.doc, m.path",
            parameters={"n": name}).get_all()
        if not info:
            print(f"Module introuvable : {name}")
            return
        n, cat, isk, doc, path = info[0]
        print(f"== {n} ==")
        print(f"  emplacement : {path}")
        print(f"  categorie   : {cat}   | skill: {isk}")
        print(f"  description : {doc}")
        print("\n  Imports :")
        for r in conn.execute(
            "MATCH (:Module {name:$n})-[:IMPORTS]->(i:Import) "
            "RETURN i.name, i.source, i.imported ORDER BY i.name",
            parameters={"n": name}).get_all():
            print("   ", r)
        print("\n  Expose :")
        for r in conn.execute(
            "MATCH (:Module {name:$n})-[:EXPOSES]->(s:Symbol) "
            "RETURN s.name, s.kind, s.lineno ORDER BY s.lineno",
            parameters={"n": name}).get_all():
            print("   ", r)
    finally:
        conn.close()
        db.close()


def main():
    # Chemins résolus ABSOLUMENT depuis la position du script, afin de fonctionner
    # depuis n'importe quel répertoire courant (sans faire 'cd' dans le repo).
    repo_root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Code-map Phoenix dans LadybugDB")
    ap.add_argument("--scan", nargs="+",
                    default=[str(repo_root / "mycroft"),
                             str(repo_root / "mycroft_lora_win")],
                    help="Répertoires à scanner (par défaut tout Mycroft + win)")
    ap.add_argument("--db", default=str(repo_root / "data" / "graph" / "module_map.lbdb"),
                    help="Chemin du .lbdb de sortie")
    ap.add_argument("--rebuild", action="store_true",
                    help="Recrée le schéma from scratch (DROP + CREATE)")
    ap.add_argument("--query", metavar="CYPHER",
                    help="Interroge le graphe existant (lecture seule)")
    ap.add_argument("--categories", action="store_true",
                    help="Liste les catégories + nombre de modules")
    ap.add_argument("--skills", action="store_true",
                    help="Liste les modules détectés comme skills")
    ap.add_argument("--module", metavar="NOM",
                    help="Détail d'un module (imports + symbols)")
    ap.add_argument("--json", action="store_true",
                    help="Sortie JSON (avec --query)")
    args = ap.parse_args()

    if args.query:
        run_query(args.db, args.query, as_json=args.json)
        return
    if args.categories:
        show_categories(args.db)
        return
    if args.skills:
        show_skills(args.db)
        return
    if args.module:
        show_module(args.db, args.module)
        return
    build(args.scan, args.db, rebuild=args.rebuild)


if __name__ == "__main__":
    main()
