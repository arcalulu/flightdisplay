#!/usr/bin/env python3
"""Outil pour les fichiers de langue de Flight display.

  python3 lang/check_lang.py --new de "Deutsch"   cree lang/de.json (toutes les cles, valeurs vides a traduire)
  python3 lang/check_lang.py de                   liste les textes non traduits et les emplacements {0} incoherents

Les textes francais sont les cles. Une valeur vide ou absente laisse le texte en francais.
Le fichier de reference pour les cles est lang/en.json.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PH = re.compile(r"\{\d+\}")


def read(code):
    with open(os.path.join(HERE, code + ".json"), encoding="utf-8-sig") as fh:
        return json.load(fh)


def main(argv):
    if len(argv) >= 2 and argv[0] == "--new":
        code, name = argv[1], (argv[2] if len(argv) > 2 else argv[1])
        path = os.path.join(HERE, code + ".json")
        if os.path.exists(path):
            print("Le fichier existe deja :", path); return 1
        ref = read("en")["strings"]
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"_meta": {"name": name}, "strings": {k: "" for k in ref}}, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print("Cree :", path, "(", len(ref), "textes a traduire ). Redemarrez webadmin pour voir la langue dans Reglages.")
        return 0
    if len(argv) != 1:
        print(__doc__); return 2
    ref, cur = read("en")["strings"], read(argv[0]).get("strings", {})
    missing = [k for k in ref if not cur.get(k)]
    bad = [k for k in ref if cur.get(k) and sorted(PH.findall(k)) != sorted(PH.findall(cur[k]))]
    for k in missing:
        print("A traduire :", repr(k))
    for k in bad:
        print("Emplacements {N} differents :", repr(k), "->", repr(cur[k]))
    print("%d texte(s) sur %d traduit(s), %d emplacement(s) incoherent(s)." % (len(ref) - len(missing), len(ref), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
