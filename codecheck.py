"""Controle statique du code, sans rien importer ni lancer (bibliotheque standard seulement) : signale les noms utilises sans avoir ete definis.

Utilise par la mise a jour de webadmin avant de relancer l'affichage : py_compile ne voit que la syntaxe, alors qu'un nom jamais defini
(fonction non importee, faute de frappe...) n'apparait qu'au demarrage du programme.

    python codecheck.py fichier.py [autre.py ...]     (code de sortie 1 si une erreur est trouvee)

Deux controles :
  1. le code qui s'execute a l'import d'un module (hors corps de fonctions) ne doit utiliser que des noms deja definis plus haut ;
  2. une fonction ne doit pas utiliser un nom global que le module ne definit nulle part.
"""
import ast
import builtins
import symtable
import sys

_MODULE_NAMES = {"__name__", "__file__", "__doc__", "__spec__", "__package__", "__loader__", "__builtins__", "__path__", "__annotations__"}


def _targets(node):
    """Noms que cette instruction (et ce qu'elle contient, hors fonctions et classes) definit dans le module."""
    out = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            continue  # le contenu appartient a un autre espace de noms
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and getattr(n, "name", None):
            out.add(n.name)
        elif isinstance(n, ast.Global):
            out.update(n.names)
        stack.extend(ast.iter_child_nodes(n))
    return out


def _loads(node):
    """Noms lus par du code execute a l'import : on saute les corps de fonctions et de classes (mais pas leurs decorateurs, valeurs par defaut, bases)
    et les variables propres aux comprehensions et aux lambdas."""
    found = []
    local = set()

    def walk(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                walk(d)
            a = n.args
            for d in list(a.defaults) + [x for x in a.kw_defaults if x is not None]:
                walk(d)
            return
        if isinstance(n, ast.ClassDef):
            for d in n.decorator_list + n.bases + [k.value for k in n.keywords]:
                walk(d)
            return
        if isinstance(n, ast.Lambda):
            for d in list(n.args.defaults) + [x for x in n.args.kw_defaults if x is not None]:
                walk(d)
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for g in n.generators:
                for t in ast.walk(g.target):
                    if isinstance(t, ast.Name):
                        local.add(t.id)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            found.append((n.id, n.lineno))
        for c in ast.iter_child_nodes(n):
            walk(c)

    walk(node)
    return [(name, line) for name, line in found if name not in local]


def check_source(src, filename="<source>"):
    """Liste de messages d'erreur (vide si tout va bien)."""
    try:
        tree = ast.parse(src, filename)
    except SyntaxError as e:
        return ["%s:%s: erreur de syntaxe : %s" % (filename, e.lineno, e.msg)]
    known = set(dir(builtins)) | _MODULE_NAMES
    errors = []
    defined = set()

    def check(node):
        if node is None:
            return
        for name, line in _loads(node):
            if name not in defined and name not in known:
                errors.append("%s:%d: le nom « %s » est utilisé avant d'être défini" % (filename, line, name))
        defined.update(_targets(node))

    def run(stmts):  # 1. code execute a l'import, dans l'ordre (les blocs if / for / with / try sont parcourus instruction par instruction)
        for s in stmts:
            if isinstance(s, (ast.If, ast.While)):
                check(s.test); run(s.body); run(s.orelse)
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                check(s.iter); defined.update(_targets(s.target)); run(s.body); run(s.orelse)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                for it in s.items:
                    check(it.context_expr)
                    if it.optional_vars is not None:
                        defined.update(_targets(it.optional_vars))
                run(s.body)
            elif isinstance(s, ast.Try) or s.__class__.__name__ == "TryStar":
                run(s.body)
                for h in s.handlers:
                    check(h.type)
                    if h.name:
                        defined.add(h.name)
                    run(h.body)
                run(s.orelse); run(s.finalbody)
            elif s.__class__.__name__ == "Match":
                check(s.subject)
                for c in s.cases:
                    defined.update(_targets(c.pattern)); check(c.guard); run(c.body)
            else:
                check(s)

    run(tree.body)
    module_defined = set(defined)
    for n in ast.walk(tree):  # noms declares globaux dans une fonction puis affectes
        if isinstance(n, ast.Global):
            module_defined.update(n.names)

    def scan(table):  # 2. noms globaux utilises dans les fonctions et classes
        for sym in table.get_symbols():
            if table.get_type() != "module" and sym.is_global() and sym.is_referenced():
                name = sym.get_name()
                if name not in module_defined and name not in known and not sym.is_assigned():
                    errors.append("%s:%d: le nom « %s » n'est défini nulle part" % (filename, table.get_lineno(), name))
        for child in table.get_children():
            scan(child)

    try:
        scan(symtable.symtable(src, filename, "exec"))
    except (SyntaxError, ValueError):
        pass
    seen = set()
    return [e for e in errors if not (e in seen or seen.add(e))]


def main(paths):
    bad = 0
    for p in paths:
        try:
            with open(p, encoding="utf-8-sig") as fh:
                src = fh.read()
        except OSError as e:
            print("%s : lecture impossible (%s)" % (p, e))
            bad += 1
            continue
        for msg in check_source(src, p):
            print(msg)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
