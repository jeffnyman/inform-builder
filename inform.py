#!/usr/bin/env python3
"""Inform front-end: run the locally built Inform 7 tools without hunting for them.

Usage:  python inform.py <command> [args]

Commands:
  where                 Show which executables and Internal folder will be used.
  ide                   Launch the Windows IDE (Build\\Inform.exe).
  compile <project>     Compile a .inform project folder the way the IDE does:
                        inform7, then inform6, into <project>\\Build\\output.ulx.
                        Flags: --z8 (Z-machine instead of Glulx), --release
                        (no debug, and inblorb packaging if Release.blurb exists).
  play <story>          Play a .ulx/.gblorb or .z?/.zblorb file in the dumb-terminal
                        glulxe or frotz that ships beside the compiler.
  inform7 [args]        Pass-through to each tool. For inform7 and inbuild,
  inbuild [args]        -internal <Internal> is added unless you supply one.
  inform6 [args]
  inblorb [args]
  intest  [args]
  inweb   [args]

Where the tools come from, in order of preference:
  1. <work>\\Windows-Inform7\\Build\\Compilers + Build\\Internal  (after `build.py integrate`;
     the pairing the IDE itself uses)
  2. the source trees: <work>\\inform\\*\\Tangled, <work>\\intest\\Tangled, <work>\\inweb\\Tangled,
     with <work>\\inform\\inform7\\Internal
Both halves always come from the same place. Override with --work DIR or $INFORM_WORK,
or force the second with --from-source.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


class Tools:
    """Resolved locations of the executables and resources."""

    def __init__(self, work, from_source=False):
        self.work = work
        ide = work / "Windows-Inform7"
        comps = ide / "Build" / "Compilers"
        if not from_source and (comps / f"inform7{EXE}").exists():
            self.origin = "IDE Build folder (integrated)"
            self.internal = ide / "Build" / "Internal"
            self.exe = {
                n: comps / f"{n}{EXE}"
                for n in (
                    "inform7",
                    "inbuild",
                    "inform6",
                    "inblorb",
                    "intest",
                    "frotz",
                    "glulxe",
                )
            }
            self.exe["inweb"] = work / "inweb" / "Tangled" / f"inweb{EXE}"
            self.ide_exe = ide / "Build" / f"Inform{EXE}"
        else:
            self.origin = "source trees (Tangled)"
            inform = work / "inform"
            self.internal = inform / "inform7" / "Internal"
            self.exe = {
                "inform7": inform / "inform7" / "Tangled" / f"inform7{EXE}",
                "inbuild": inform / "inbuild" / "Tangled" / f"inbuild{EXE}",
                "inform6": inform / "inform6" / "Tangled" / f"inform6{EXE}",
                "inblorb": inform / "inblorb" / "Tangled" / f"inblorb{EXE}",
                "intest": work / "intest" / "Tangled" / f"intest{EXE}",
                "inweb": work / "inweb" / "Tangled" / f"inweb{EXE}",
                "frotz": inform
                / "inform6"
                / "Tests"
                / "Assistants"
                / "dumb-frotz"
                / f"dumb-frotz{EXE}",
                "glulxe": inform
                / "inform6"
                / "Tests"
                / "Assistants"
                / "dumb-glulx"
                / "glulxe"
                / f"glulxe{EXE}",
            }
            self.ide_exe = ide / "Build" / f"Inform{EXE}"
        # The IDE passes -external <Documents>\Inform; use it if the folder exists.
        docs = Path.home() / "Documents" / "Inform"
        self.external = docs if docs.is_dir() else None

    def need(self, name):
        p = self.exe.get(name)
        if not p or not p.exists():
            die(
                f"{name} not found at {p}. Build it first: python build.py all"
                + (
                    " && python build.py integrate"
                    if name in ("frotz", "glulxe")
                    else ""
                )
            )
        return p


def run(cmd, cwd=None, stdin=None):
    print(
        "$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True
    )
    return subprocess.call(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None, stdin=stdin
    )


# --- Commands ---------------------------------------------------------------


def cmd_where(t):
    print(f"Using: {t.origin}")
    print(
        f"  {'Internal':10} {t.internal}  {'ok' if t.internal.is_dir() else 'MISSING'}"
    )
    for name, p in t.exe.items():
        print(f"  {name:10} {p}  {'ok' if p.exists() else 'MISSING'}")
    print(f"  {'IDE':10} {t.ide_exe}  {'ok' if t.ide_exe.exists() else 'not built'}")
    print(
        f"  {'external':10} {t.external or '(none; ~/Documents/Inform does not exist)'}"
    )


def cmd_ide(t, args):
    if not t.ide_exe.exists():
        die(f"IDE not built at {t.ide_exe}: python build.py ide")
    # Detach so this script can return while the IDE stays open.
    flags = (
        subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        if IS_WINDOWS
        else 0
    )
    subprocess.Popen(
        [str(t.ide_exe)] + args, cwd=str(t.ide_exe.parent), creationflags=flags
    )
    print(f"Launched {t.ide_exe}")


def project_dir(arg):
    p = Path(arg).resolve()
    if not p.is_dir():
        die(f"{p} is not a folder")
    if not (p / "Source" / "story.ni").exists():
        die(f"{p} has no Source\\story.ni; is it an Inform project?")
    return p


def cmd_compile(t, args):
    z8 = "--z8" in args
    release = "--release" in args
    rest = [a for a in args if not a.startswith("--")]
    if len(rest) != 1:
        die("usage: inform.py compile <project.inform> [--z8] [--release]")
    proj = project_dir(rest[0])
    # The IDE creates uuid.txt when it makes a project; inform7 insists on it.
    if not (proj / "uuid.txt").exists():
        (proj / "uuid.txt").write_text(str(uuid.uuid4()) + "\n")
        print("Created uuid.txt")
    (proj / "Build").mkdir(exist_ok=True)

    # Mirrors ProjectSettings::GetInformSwitches and the -format names in the IDE.
    fmt = ("Inform6/16" if z8 else "Inform6/32") + ("" if release else "d")
    ext = "z8" if z8 else "ulx"
    i6_switches = "-w" + ("~S~D" if release else "SD") + ("v8" if z8 else "G")

    cmd = [t.need("inform7"), "-internal", t.internal]
    if t.external:
        cmd += ["-external", t.external]
    cmd += ["-project", proj, f"-format={fmt}"]
    if run(cmd) != 0:
        die("inform7 failed (see Build\\Problems.html in the project)", 2)

    rc = run(
        [
            t.need("inform6"),
            i6_switches,
            "+include_path=..\\Source,.\\",
            "auto.inf",
            f"output.{ext}",
        ],
        cwd=proj / "Build",
    )
    if rc != 0:
        die("inform6 failed", 3)
    out = proj / "Build" / f"output.{ext}"
    print(f"\nStory file: {out}  ({out.stat().st_size / 1e3:.0f} KB)")

    if release and (proj / "Release.blurb").exists():
        blorb = "zblorb" if z8 else "gblorb"
        if (
            run(
                [t.need("inblorb"), "Release.blurb", f"Build\\output.{blorb}"], cwd=proj
            )
            == 0
        ):
            print(f"Blorb:      {proj / 'Build' / ('output.' + blorb)}")
    print(f'Play it:    python inform.py play "{out}"')


def cmd_play(t, args):
    if len(args) != 1:
        die("usage: inform.py play <storyfile>")
    story = Path(args[0]).resolve()
    if not story.exists():
        die(f"{story} not found")
    ext = story.suffix.lower()
    terp = (
        "frotz"
        if ext in (".z3", ".z4", ".z5", ".z6", ".z8", ".zblorb", ".zlb")
        else "glulxe"
    )
    print(f"({terp}: dumb-terminal interpreter; type 'quit' to leave)")
    sys.exit(run([t.need(terp), story]))


def cmd_passthrough(t, name, args):
    exe = t.need(name)
    if name in ("inform7", "inbuild") and "-internal" not in args:
        args = ["-internal", str(t.internal)] + args
    sys.exit(run([exe] + args))


def main(argv):
    args = list(argv)
    work = Path(os.environ.get("INFORM_WORK", HERE.parent / "_informing"))
    from_source = False
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--work":
            i += 1
            work = Path(args[i])
        elif args[i] == "--from-source":
            from_source = True
        elif args[i] in ("-h", "--help", "help") and not rest:
            print(__doc__)
            return 0
        else:
            rest.append(args[i])
        i += 1
    if not rest:
        print(__doc__)
        return 2
    t = Tools(work.resolve(), from_source)
    cmd, params = rest[0], rest[1:]
    if cmd == "where":
        cmd_where(t)
    elif cmd == "ide":
        cmd_ide(t, params)
    elif cmd == "compile":
        cmd_compile(t, params)
    elif cmd == "play":
        cmd_play(t, params)
    elif cmd in ("inform7", "inbuild", "inform6", "inblorb", "intest", "inweb"):
        cmd_passthrough(t, cmd, params)
    else:
        die(f"unknown command '{cmd}'. Try: python inform.py help")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
