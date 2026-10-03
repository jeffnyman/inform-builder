#!/usr/bin/env python3

"""Inform easy builder: compile inweb, intest and the core Inform tools.

On Windows this uses a portable toolchain (llvm-mingw clang + GNU make + the
busybox shell that llvm-mingw bundles), downloaded into ./toolchain by `setup`.
Nothing is installed system-wide; delete the folder to uninstall. On Linux and
macOS it uses the system clang and make.

Usage:  python build.py <command> [options]

Commands:
  doctor            Check prerequisites; show versions, paths and repo states.
  setup             Download and unpack the portable toolchain (Windows only).
  pins              Check the three repos out at the known-good commits (needs git).
  inweb [--first]   Build inweb.  --first forces the upstream bootstrap script.
  intest [--first]  Build intest.
  inform [--first]  Build the core Inform tools (about 3.5 minutes).
  all               setup, inweb, intest, inform, then test.
  test [CASE|all]   Run one intest case (default: Acidity) or the whole suite.
  integrate         Copy the built tools and resources into a Windows IDE checkout
                    (Build/Compilers, Build/Internal, Build/Documentation). Uses
                    --ide DIR, default <work>/Windows-Inform7.
  mac-integrate     Copy the official Inform.app (--app PATH, default
                    /Applications/Inform.app) with the built tools, Internal and
                    documentation swapped in, renamed (--name, default e.g.
                    "Inform 10.2") with its own bundle identifier (--bundle-id),
                    signed ad hoc, into --out DIR (default ~/Applications).
  ide-libs          Fetch the third-party libraries and helper repos that
                    Inform7.exe needs, into the layout its project files expect.
  ide               Build Inform.exe with MSBuild from Visual Studio Build Tools
                    (toolset forced to the one installed, e.g. v143).
  ide-interpreters  Clone the Frotz, Glulxe and Git repos and build the Story-tab
                    interpreters into Build/Interpreters.
  shell [--posix]   Open an interactive shell with the toolchain on PATH.
  env [--ps|--cmd]  Print lines that put the toolchain on PATH in your shell.

Options:
  --work DIR        Folder holding inweb/, intest/, inform/ as siblings.
                    Default: $INFORM_WORK, else ../_informing next to this file.
  --platform NAME   Inweb platform name (windows, linux, macos, macosintel, unix).
                    Default: detected from the OS.

Requires Python 3.8 or later and nothing from PyPI.
"""

import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import NoReturn

# --- Configuration ----------------------------------------------------------
# Override any value with the environment variable of the same name.

HERE = Path(__file__).resolve().parent
TOOLCHAIN = HERE / "toolchain"

LLVM_MINGW_TAG = os.environ.get("LLVM_MINGW_TAG", "20260922")
LLVM_MINGW_FLAVOUR = os.environ.get("LLVM_MINGW_FLAVOUR", "ucrt-x86_64")
EZWINPORTS_MAKE = os.environ.get("EZWINPORTS_MAKE", "make-4.4.1-without-guile-w32-bin")

# Known-good source combination, verified together on 2 October 2026.
# inweb HEAD 705085d7 (28 Sep 2026) refactored the Markdown renderer and removed
# Markdown::render_extended, which inform 10.2.0-beta+6Y13 still calls.
PINS = {
    "inweb": os.environ.get("INWEB_REF", "e5329237"),  # 9.0-beta+1C30, 21 Aug 2026
    "intest": os.environ.get("INTEST_REF", "00857f4"),  # 2.2.0-beta+1A76, 24 Apr 2026
    "inform": os.environ.get(
        "INFORM_REF", "5c7ba42b7"
    ),  # 10.2.0-beta+6Y13, 24 Jun 2026
}

IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""

# --- Small helpers ----------------------------------------------------------


def die(msg, code=1) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def say(msg):
    print(f"\n==> {msg}", flush=True)


def detect_platform():
    s = platform.system()
    if s == "Windows":
        return "windows"
    if s == "Darwin":
        return "macos" if platform.machine() == "arm64" else "macosintel"
    if s == "Linux":
        return "linux"
    return "unix"


def toolchain_dirs():
    """Directories to prepend to PATH, in priority order. Windows only."""
    if not IS_WINDOWS:
        return []
    return [
        TOOLCHAIN / "llvm-mingw" / "bin",
        TOOLCHAIN / "make" / "bin",  # GNU make must shadow busybox's own make
        TOOLCHAIN / "llvm-mingw" / "busybox" / "bin",  # sh, cp, rm, mkdir for recipes
    ]


def toolchain_present():
    if not IS_WINDOWS:
        return bool(shutil.which("clang") and shutil.which("make"))
    return all(
        (d / exe).exists()
        for d, exe in [
            (TOOLCHAIN / "llvm-mingw" / "bin", "clang.exe"),
            (TOOLCHAIN / "make" / "bin", "make.exe"),
            (TOOLCHAIN / "llvm-mingw" / "busybox" / "bin", "sh.exe"),
        ]
    )


def build_env():
    env = dict(os.environ)
    dirs = [str(d) for d in toolchain_dirs()]
    if dirs:
        env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    return env


def tool(name):
    """Path to bash or make: the portable one on Windows, the system one elsewhere."""
    if IS_WINDOWS:
        if name == "bash":
            return str(TOOLCHAIN / "llvm-mingw" / "busybox" / "bin" / "bash.exe")
        if name == "make":
            return str(TOOLCHAIN / "make" / "bin" / "make.exe")
    return name


SKEW_HINT = (
    "This looks like version skew between inweb and inform, not a toolchain fault.\n"
    "Run `python build.py pins` to use the verified commit combination, "
    "then rebuild with --first."
)


def run(cmd, cwd, check=True):
    """Run a command, streaming output, and spot the known version-skew symptom."""
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    skew = False
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=build_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout is None:
        die("failed to capture command output")
    for line in proc.stdout:
        sys.stdout.write(line)
        if "undeclared function" in line and "__" in line:
            skew = True
    rc = proc.wait()
    if rc != 0 and check:
        if skew:
            print("\n" + SKEW_HINT, file=sys.stderr)
        die(f"command failed with exit code {rc}", rc)
    return rc


def version_of(exe, cwd, flag="-version"):
    try:
        out = subprocess.run(
            [str(exe), flag],
            cwd=str(cwd),
            env=build_env(),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001
        return f"(could not run: {e})"


def git(repo, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


# --- Commands ---------------------------------------------------------------


def download(url, dest, label):
    if dest.exists():
        print(f"{dest.name} already downloaded.")
        return
    say(f"Downloading {label}")
    print(f"  {url}")
    tmp = dest.with_suffix(".part")

    def progress(blocks, bsize, total):
        if total > 0:
            done = min(blocks * bsize, total)
            sys.stdout.write(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, tmp, reporthook=progress)
    print()
    tmp.rename(dest)


def cmd_setup(work, plat):
    if not IS_WINDOWS:
        say("Non-Windows platform: using system clang and make")
        for t in ("clang", "make"):
            if not shutil.which(t):
                die(
                    f"{t} not found. Install it (e.g. `sudo apt install clang make`, "
                    f"or `xcode-select --install` on macOS)."
                )
        print(version_of("clang", work, "--version"))
        print(version_of("make", work, "--version"))
        return

    dl = TOOLCHAIN / "downloads"
    dl.mkdir(parents=True, exist_ok=True)

    llvm_name = f"llvm-mingw-{LLVM_MINGW_TAG}-{LLVM_MINGW_FLAVOUR}"
    llvm_url = (
        f"https://github.com/mstorsjo/llvm-mingw/releases/download/"
        f"{LLVM_MINGW_TAG}/{llvm_name}.zip"
    )
    make_url = (
        f"https://sourceforge.net/projects/ezwinports/files/"
        f"{EZWINPORTS_MAKE}.zip/download"
    )

    if not (TOOLCHAIN / "llvm-mingw" / "bin" / "clang.exe").exists():
        zip_path = dl / f"{llvm_name}.zip"
        download(llvm_url, zip_path, "llvm-mingw (about 190 MB)")
        say("Unpacking llvm-mingw (about 735 MB on disk)")
        shutil.rmtree(TOOLCHAIN / "llvm-mingw", ignore_errors=True)
        shutil.rmtree(TOOLCHAIN / llvm_name, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(TOOLCHAIN)
        (TOOLCHAIN / llvm_name).rename(TOOLCHAIN / "llvm-mingw")
    else:
        print("llvm-mingw already present.")

    if not (TOOLCHAIN / "make" / "bin" / "make.exe").exists():
        zip_path = dl / f"{EZWINPORTS_MAKE}.zip"
        download(make_url, zip_path, "GNU make")
        say("Unpacking make")
        shutil.rmtree(TOOLCHAIN / "make", ignore_errors=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(TOOLCHAIN / "make")
    else:
        print("make already present.")

    say("Toolchain ready")
    print(
        "  "
        + version_of(TOOLCHAIN / "llvm-mingw" / "bin" / "clang.exe", HERE, "--version")
    )
    print("  " + version_of(TOOLCHAIN / "make" / "bin" / "make.exe", HERE, "--version"))
    print(
        "  "
        + version_of(
            TOOLCHAIN / "llvm-mingw" / "busybox" / "bin" / "busybox.exe", HERE, "--help"
        )
    )
    print("\nThe toolchain/downloads folder is only a cache and can be deleted.")


def need_toolchain():
    if not toolchain_present():
        die("toolchain not present. Run: python build.py setup")


def need_repo(work, name):
    if not (work / name).is_dir():
        die(
            f"no {name}/ in {work}. Clone it: "
            f"git clone https://github.com/ganelson/{name}.git"
        )


def cmd_inweb(work, plat, first):
    need_toolchain()
    need_repo(work, "inweb")
    if first or not (work / "inweb" / "inweb.mk").exists():
        run([tool("bash"), "inweb/scripts/first.sh", plat], work)
    else:
        run([tool("make"), "-f", "inweb/inweb.mk"], work)
    print(version_of(work / "inweb" / "Tangled" / f"inweb{EXE}", work))


def cmd_intest(work, plat, first):
    need_toolchain()
    need_repo(work, "intest")
    if not (work / "inweb" / "Tangled" / f"inweb{EXE}").exists():
        die("build inweb first: python build.py inweb")
    if first or not (work / "intest" / "intest.mk").exists():
        run([tool("bash"), "intest/scripts/first.sh"], work)
    else:
        run([tool("make"), "-f", "intest/intest.mk"], work)
    print(version_of(work / "intest" / "Tangled" / f"intest{EXE}", work))


def cmd_inform(work, plat, first):
    need_toolchain()
    need_repo(work, "inform")
    for dep in ("inweb", "intest"):
        if not (work / dep / "Tangled" / f"{dep}{EXE}").exists():
            die(f"build {dep} first: python build.py {dep}")
    inform = work / "inform"
    if first or not (inform / "makefile").exists():
        run([tool("bash"), "scripts/first.sh"], inform)
    else:
        run([tool("make")], inform)
    print(version_of(inform / "inform7" / "Tangled" / f"inform7{EXE}", inform))


def cmd_test(work, plat, case):
    need_toolchain()
    need_repo(work, "inform")
    inform = work / "inform"
    intest = work / "intest" / "Tangled" / f"intest{EXE}"
    if not intest.exists():
        die("build intest first: python build.py intest")
    if case == "all":
        run([tool("make"), "check"], inform)
    else:
        run([str(intest), "inform7", "-show", case], inform)


# Executables the IDE expects in Build/Compilers, as (settings symbol, path
# relative to the inform checkout). frotz and glulxe here are the dumb-terminal
# builds used by intest for extension testing; the Story tab uses its own
# interpreters from Build/Interpreters, which the IDE's Interpreters.sln builds.
IDE_TOOLS = [
    ("INBLORB", "inblorb/Tangled/inblorb"),
    ("INFORM6", "inform6/Tangled/inform6"),
    ("INFORM7", "inform7/Tangled/inform7"),
    ("INBUILD", "inbuild/Tangled/inbuild"),
    ("INTEST", "../intest/Tangled/intest"),
    ("FROTZ", "inform6/Tests/Assistants/dumb-frotz/dumb-frotz"),
    ("GLULXE", "inform6/Tests/Assistants/dumb-glulx/glulxe/glulxe"),
]

# forceintegration minus the two targets that copy executables (done in Python,
# because busybox cp lacks Cygwin's implicit ".exe" handling).
IDE_RESOURCE_TARGETS = [
    "forcetransferpreform",
    "forcetransferindext",
    "forcetransferkits",
    "forcetransferextensions",
    "forcetransferinwebresources",
    "forcetransferimages",
    "forcetransferotherinternals",
    "forcetransferadvice",
    "forcetransferdocumentation",
    "forcetransferoutcomepages",
    "forcetransfertemplates",
    "forcetransferdelia",
]


def link_dir(link, target):
    """Make `link` refer to directory `target`: a junction on Windows, a symlink elsewhere."""
    if link.exists():
        return "exists"
    if IS_WINDOWS:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
        return "junction"
    link.symlink_to(target, target_is_directory=True)
    return "symlink"


def cmd_integrate(work, plat, ide):
    need_toolchain()
    for name in ("inweb", "intest", "inform"):
        need_repo(work, name)
    ide = Path(ide) if ide else work / "Windows-Inform7"
    if not ide.is_dir():
        die(
            f"no Windows IDE checkout at {ide}. Clone "
            f"https://github.com/DavidKinder/Windows-Inform7.git there, or pass --ide DIR"
        )
    dist = ide / "Distribution"
    settings_file = dist / "make-integration-settings.mk"
    if not settings_file.exists():
        die(f"{settings_file} not found; is {ide} really a Windows-Inform7 checkout?")

    say("Linking the source repos into the IDE's Distribution folder")
    for name in ("inweb", "intest", "inform"):
        how = link_dir(dist / name, (work / name).resolve())
        print(f"  Distribution/{name:7} {how}")
    inform = dist / "inform"

    settings = {}
    for line in settings_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            settings[k.strip()] = v.strip()
    comps = (inform / settings["BUILTINCOMPS"]).resolve()

    say("Making sure the tools are up to date (make, with integration settings active)")
    run([tool("make")], inform)

    say(f"Copying executables to {comps}")
    comps.mkdir(parents=True, exist_ok=True)
    for sym, rel in IDE_TOOLS:
        src = inform / (rel + EXE)
        if not src.exists():
            die(f"{src} missing; run `python build.py inform` first")
        dest = comps / (settings[sym + "NAME"] + EXE)
        shutil.copy2(src, dest)
        print(f"  {dest.name:14} {dest.stat().st_size / 1e6:6.1f} MB")

    say("Transferring Internal resources and documentation (upstream make targets)")
    if IS_WINDOWS:
        run([tool("make")] + IDE_RESOURCE_TARGETS, inform)
    else:
        run([tool("make"), "forceintegration"], inform)

    say("Result")
    for key in ("BUILTINCOMPS", "INTERNAL", "BUILTINHTML"):
        d = (inform / settings[key]).resolve()
        n = sum(1 for p in d.rglob("*") if p.is_file()) if d.is_dir() else 0
        print(f"  {d}  ({n} files)")
    print(
        "\nThe IDE launches <AppDir>\\Compilers\\inform7.exe with -internal <AppDir>\\Internal,"
    )
    print("so an Inform7.exe built from this checkout now runs the 10.2 compiler.")


# --- macOS: feed the build into a copy of the installed Inform.app ----------
# The Mac app looks its tools up by name in Contents/MacOS (inform7 is "ni",
# inblorb is "cBlorb") and passes Contents/Resources/Internal to ni with
# -internal. So a copy of the official app with those swapped is a Mac IDE
# running this build, and no Xcode is needed. The copy gets its own name and
# bundle identifier so it can sit beside the official app.

MAC_APP_SOURCE = Path("/Applications/Inform.app")
MAC_BUNDLE_ID = os.environ.get(
    "MAC_BUNDLE_ID", "com.inform7.inform-compiler.source-build"
)
MAC_SETTINGS_MARKER = (
    "# Written by inform-builder mac-integrate; removed when it finishes."
)

# Upstream's make-integration-settings.mk for this layout. The paths must not
# contain spaces, so they point at a staging copy in a temporary folder.
MAC_SETTINGS = """{marker}
INTEGRATION = TRUE
BUILTINCOMPS = {c}/MacOS
INTERNAL = {c}/Resources/Internal
BUILTINHTML = {c}/Resources
BUILTINHTMLINNER = {c}/Resources/en.lproj
ADVICEHTML = {c}/Resources/en.lproj
INBLORBNAME = cBlorb
INFORM6NAME = inform6
INFORM7NAME = ni
INTESTNAME = intest
INBUILDNAME = inbuild
FROTZNAME = dumb-frotz
GLULXENAME = dumb-glulxe
HTMLPLATFORM = macos
"""


def bundle_id_of(app):
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier")
    except (OSError, ValueError):
        return None


def cmd_mac_integrate(work, plat, app_src, out_dir, name, bundle_id):
    if platform.system() != "Darwin":
        die("mac-integrate is for macOS; on Windows use `integrate`")
    for repo in ("inweb", "intest", "inform"):
        need_repo(work, repo)
    inform = work / "inform"
    for _, rel in IDE_TOOLS:
        if not (inform / rel).exists():
            die(f"{inform / rel} missing; run `python build.py all` first")

    app_src = Path(app_src) if app_src else MAC_APP_SOURCE
    if not (app_src / "Contents" / "MacOS" / "ni").exists():
        die(
            f"no Inform.app at {app_src}. Install the official Mac app from "
            "https://inform7.com, or pass --app PATH"
        )
    bundle_id = bundle_id or MAC_BUNDLE_ID
    if bundle_id_of(app_src) == bundle_id:
        die(
            f"{app_src} is itself a mac-integrate build; point --app at the official app"
        )

    if not name:
        ver = version_of(inform / "inform7/Tangled/inform7", inform)
        nums = next((w for w in ver.split() if w[:1].isdigit()), "")
        name = "Inform " + ".".join(nums.split("-")[0].split(".")[:2])
    out_dir = Path(out_dir).expanduser() if out_dir else Path.home() / "Applications"
    dest = out_dir / f"{name}.app"
    if dest.exists() and bundle_id_of(dest) != bundle_id:
        die(f"{dest} exists and was not made by mac-integrate; not overwriting it")

    settings_file = work / "make-integration-settings.mk"
    if settings_file.exists() and MAC_SETTINGS_MARKER not in settings_file.read_text(
        encoding="utf-8"
    ):
        die(f"{settings_file} already exists and is not ours; move it aside first")

    with tempfile.TemporaryDirectory(prefix="inform-mac-") as tmp:
        stage = Path(tmp) / "Inform.app"
        contents = stage / "Contents"
        if " " in str(contents):
            die(f"temporary folder {tmp} contains a space; set TMPDIR elsewhere")

        say(f"Copying {app_src} to a staging folder")
        # No extended attributes: quarantine and Finder info would break codesign.
        run(["ditto", "--noextattr", "--noacl", str(app_src), str(stage)], work)

        # The official app's Internal and HTML pages are for an older Inform. Its
        # 10.1 kits in Internal/Inter make 10.2 fail with "Web Syntax Version has
        # been withdrawn", so both are replaced rather than overlaid. The .strings
        # and .nib files in en.lproj belong to the app and are kept.
        shutil.rmtree(contents / "Resources" / "Internal", ignore_errors=True)
        lproj = contents / "Resources" / "en.lproj"
        for p in list(lproj.glob("*.html")) + [lproj / "xrefs.txt"]:
            if p.exists():
                p.unlink()

        say(
            "Transferring tools, Internal and documentation (upstream forceintegration)"
        )
        settings_file.write_text(
            MAC_SETTINGS.format(marker=MAC_SETTINGS_MARKER, c=contents),
            encoding="utf-8",
        )
        try:
            run([tool("make"), "forceintegration"], inform)
        finally:
            settings_file.unlink()

        say(f"Renaming to '{name}' with bundle identifier {bundle_id}")
        plist_path = contents / "Info.plist"
        with open(plist_path, "rb") as f:
            info = plistlib.load(f)
        info["CFBundleIdentifier"] = bundle_id
        info["CFBundleName"] = name
        info["CFBundleDisplayName"] = name
        with open(plist_path, "wb") as f:
            plistlib.dump(info, f)

        # Changing files broke Apple's signature, and macOS kills a binary inside a
        # bundle whose seal is broken. Sign the whole bundle ad hoc; this needs no
        # Apple developer account and the app runs on this Mac only.
        say("Signing ad hoc")
        run(["codesign", "--force", "--deep", "--sign", "-", str(stage)], work)
        run(["codesign", "--verify", "--deep", "--strict", str(stage)], work)

        if dest.exists():
            say(f"Replacing the previous build at {dest}")
            try:
                shutil.rmtree(dest)
            except OSError as e:
                die(
                    f"could not remove {dest}: {e}\nIf this is 'Operation not permitted', "
                    "give your terminal App Management access in System Settings > "
                    "Privacy & Security, or delete the old app in Finder"
                )
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage), str(dest))

    say("Result")
    print(f"  {dest}")
    print(f"  {version_of(dest / 'Contents/MacOS/ni', work)}")
    print(f"  bundle identifier {bundle_id}")
    print(
        f"\nOpen it with: open '{dest}'\n"
        "It shares ~/Library/Inform (installed extensions and documentation) with the\n"
        "official app, so an extension installed in one is seen by the other."
    )


# --- Windows IDE: third-party libraries and MSBuild -------------------------
# Versions pinned 2 October 2026. The IDE's project files compile most of these
# from source, so what matters is the source layout under <root>/Libraries/<name>,
# where <root> is two levels above the Windows-Inform7 checkout (the vcxproj
# uses ..\..\..\Libraries). Only libjpeg-turbo is consumed as a prebuilt .lib.
IDE_LIB_VERSIONS = {
    "zlib": os.environ.get("ZLIB_VER", "1.3.2"),
    "libpng": os.environ.get("LIBPNG_VER", "1.6.59"),
    "jpeg": os.environ.get("LIBJPEG_TURBO_VER", "3.2.0"),
    "libogg": os.environ.get("LIBOGG_VER", "1.3.6"),
    "libvorbis": os.environ.get("LIBVORBIS_VER", "1.3.7"),
    # 1.7.4 (27 Sep 2026) added hunspelltrace.cxx, which the IDE project does not
    # list, so its symbols go unresolved at link time. 1.7.3 is the last release
    # with the ten-file layout the vcxproj compiles.
    "hunspell": os.environ.get("HUNSPELL_VER", "1.7.3"),
    "json": os.environ.get("NLOHMANN_JSON_VER", "3.12.0"),
    "libcef": os.environ.get("CEF_VER", "144.0.12+g1a1008c+chromium-144.0.7559.110"),
}
SEVENZIP_VER = "2301"  # 7-Zip, used only to open the libjpeg-turbo NSIS installer without running it


def ide_lib_sources():
    v = IDE_LIB_VERSIONS
    return {
        "zlib": f"https://zlib.net/zlib-{v['zlib']}.tar.gz",
        "libpng": f"https://download.sourceforge.net/libpng/libpng-{v['libpng']}.tar.gz",
        "jpeg": (
            f"https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/"
            f"{v['jpeg']}/libjpeg-turbo-{v['jpeg']}-vc-x64.exe"
        ),
        "libogg": f"https://github.com/xiph/ogg/releases/download/v{v['libogg']}/libogg-{v['libogg']}.tar.gz",
        "libvorbis": (
            f"https://github.com/xiph/vorbis/releases/download/"
            f"v{v['libvorbis']}/libvorbis-{v['libvorbis']}.tar.gz"
        ),
        "minimp3": "https://github.com/lieff/minimp3/archive/refs/heads/master.zip",
        "hunspell": (
            f"https://github.com/hunspell/hunspell/releases/download/"
            f"v{v['hunspell']}/hunspell-{v['hunspell']}.tar.gz"
        ),
        "json": f"https://github.com/nlohmann/json/releases/download/v{v['json']}/include.zip",
        "libcef": (
            f"https://cef-builds.spotifycdn.com/cef_binary_{v['libcef']}"
            f"_windows64_minimal.tar.bz2".replace("+", "%2B")
        ),
    }


def unpack(archive, dest, strip_top=True):
    """Unpack a .zip/.tar.gz/.tar.bz2 into dest. With strip_top, the archive's
    single top-level folder is removed so its contents land directly in dest."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        tmp = Path(tmp)
        name = archive.name.lower()
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                t.extractall(tmp)
        entries = list(tmp.iterdir())
        src = (
            entries[0]
            if strip_top and len(entries) == 1 and entries[0].is_dir()
            else tmp
        )
        for item in src.iterdir():
            target = dest / item.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            shutil.move(str(item), str(target))


def ensure_7z(dl):
    """Portable full 7-Zip (7z.exe + 7z.dll), needed for its NSIS reader. The
    reduced 7zr/7za builds cannot open NSIS installers, so we fetch 7zr.exe and
    use it to unpack 7-Zip's own self-extracting installer, which is a plain 7z
    SFX archive. Nothing is run or registered."""
    sz = TOOLCHAIN / "7zip"
    if (sz / "7z.exe").exists() and (sz / "7z.dll").exists():
        return sz / "7z.exe"
    sz.mkdir(parents=True, exist_ok=True)
    download(
        "https://www.7-zip.org/a/7zr.exe", sz / "7zr.exe", "7zr.exe (7-Zip bootstrap)"
    )
    sfx = dl / f"7z{SEVENZIP_VER}-x64.exe"
    download(
        f"https://www.7-zip.org/a/{sfx.name}", sfx, "7-Zip (self-extracting archive)"
    )
    subprocess.run(
        [
            str(sz / "7zr.exe"),
            "e",
            str(sfx),
            f"-o{sz}",
            "7z.exe",
            "7z.dll",
            "License.txt",
            "-y",
        ],
        check=True,
        capture_output=True,
    )
    return sz / "7z.exe"


def clone_if_missing(url, dest, marker):
    if (dest / marker).exists():
        print(f"  {dest}  already present")
        return
    if not shutil.which("git"):
        die(f"git is needed to clone {url} into {dest}")
    say(f"Cloning {url}")
    subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=True)


def cmd_ide_libs(work, plat, ide):
    ide = Path(ide) if ide else work / "Windows-Inform7"
    if not (ide / "Inform7" / "Inform7.sln").exists():
        die(f"no Windows IDE checkout at {ide}; pass --ide DIR")
    root = ide.parent.parent  # vcxproj: ..\..\..\Libraries from <ide>\Inform7
    libs = root / "Libraries"
    glk = ide.parent / "Glk"  # vcxproj: ..\..\Glk
    dl = TOOLCHAIN / "downloads"
    dl.mkdir(parents=True, exist_ok=True)
    say(f"Library root: {libs}")
    print(f"  Glk helper repo: {glk}")

    # David Kinder's own helper repos: patched MFC helpers + libmodplug, and Glk.
    clone_if_missing("https://github.com/DavidKinder/Libraries.git", libs, "mfc")
    clone_if_missing("https://github.com/DavidKinder/Windows-Glk.git", glk, "Include")

    src = ide_lib_sources()
    for name in ("zlib", "libpng", "libogg", "libvorbis", "minimp3", "json", "libcef"):
        dest = libs / name
        if dest.exists() and any(dest.iterdir()):
            print(f"  {name:10} already present")
            continue
        archive = dl / Path(src[name].replace("%2B", "+")).name
        download(src[name], archive, name)
        say(f"Unpacking {name}")
        unpack(archive, dest, strip_top=(name != "json"))

    # hunspell: the project wants the contents of src/hunspell at Libraries/hunspell.
    dest = libs / "hunspell"
    if not (dest / "hunspell.cxx").exists():
        archive = dl / Path(src["hunspell"]).name
        download(src["hunspell"], archive, "hunspell")
        say("Unpacking hunspell (src/hunspell only)")
        with tempfile.TemporaryDirectory(dir=libs) as tmp:
            unpack(archive, Path(tmp) / "h")
            dest.mkdir(exist_ok=True)
            for f in (Path(tmp) / "h" / "src" / "hunspell").iterdir():
                shutil.copy2(f, dest / f.name)
    else:
        print("  hunspell   already present")

    # libjpeg-turbo: prebuilt VC x64 package is an NSIS installer; open it with 7-Zip
    # rather than running it, so nothing is registered with Windows.
    dest = libs / "jpeg"
    if not (dest / "lib64" / "jpeg-static.lib").exists():
        archive = dl / Path(src["jpeg"]).name
        download(src["jpeg"], archive, "libjpeg-turbo (VC x64 package)")
        sevenzip = ensure_7z(dl)
        say("Extracting libjpeg-turbo with 7-Zip (NSIS reader)")
        shutil.rmtree(dest, ignore_errors=True)
        subprocess.run(
            [
                str(sevenzip),
                "x",
                "-tNsis",
                str(archive),
                f"-o{dest}",
                "-y",
                "-x!$PLUGINSDIR",
                "-x!$SYSDIR",
                "-x![NSIS].nsi",
            ],
            check=True,
            capture_output=True,
        )
        if (dest / "lib").exists():
            (dest / "lib").rename(dest / "lib64")  # the IDE README's rename step
    else:
        print("  jpeg       already present")

    # libpng: generate pnglibconf.h from the prebuilt one, minus write support
    # (the IDE README's edit step: drop PNG_SAVE_*, PNG_SIMPLIFIED_WRITE_*, PNG_WRITE_*).
    conf = libs / "libpng" / "pnglibconf.h"
    if not conf.exists():
        say("Creating libpng/pnglibconf.h without write support")
        lines = (
            (libs / "libpng" / "scripts" / "pnglibconf.h.prebuilt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        keep = [
            ln
            for ln in lines
            if not any(
                ln.startswith(f"#define {p}")
                for p in ("PNG_SAVE_", "PNG_SIMPLIFIED_WRITE_", "PNG_WRITE_")
            )
        ]
        conf.write_text("\n".join(keep) + "\n", encoding="utf-8")
        print(f"  dropped {len(lines) - len(keep)} definitions")

    say("Library layout")
    for name in sorted(
        p.name for p in libs.iterdir() if p.is_dir() and not p.name.startswith(".")
    ):
        n = sum(1 for p in (libs / name).rglob("*") if p.is_file())
        print(f"  {name:12} {n:6} files")


# Source tweaks needed to compile the IDE with an older toolset than it targets.
# Each entry: (file relative to the IDE checkout, text to find, replacement).
# Applied idempotently; harmless on the newer toolset because of the #if guards.
IDE_COMPAT_PATCHES = [
    (
        "Inform7/FindAllHelper.cpp",
        (
            "  case std::regex_constants::_Error_syntax:\n"
            '    return "Syntax error in find expression.";\n'
        ),
        (
            "#if defined(_MSVC_STL_VERSION) && _MSVC_STL_VERSION >= 145\n"
            "  // _Error_syntax is an MSVC-internal code first present in the VS 2026 STL.\n"
            "  case std::regex_constants::_Error_syntax:\n"
            '    return "Syntax error in find expression.";\n'
            "#endif\n"
        ),
    ),
]


def apply_compat_patches(ide):
    for rel, old, new in IDE_COMPAT_PATCHES:
        path = ide / rel
        text = path.read_text(encoding="utf-8")
        if new in text:
            print(f"  {rel}: compatibility patch already applied")
        elif old in text:
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            print(
                f"  {rel}: applied compatibility patch (guarded #if; revert with git checkout)"
            )
        else:
            print(f"  {rel}: pattern not found; upstream may have changed, skipping")


def find_msbuild():
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.exists():
        die(
            "vswhere.exe not found: install Visual Studio Build Tools (Desktop development with C++)"
        )
    out = (
        subprocess.run(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.Component.MSBuild",
                "-find",
                r"MSBuild\**\Bin\MSBuild.exe",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        .stdout.strip()
        .splitlines()
    )
    if not out:
        die("MSBuild not found via vswhere")
    return Path(out[0])


def installed_toolsets(msbuild):
    # <VS>\MSBuild\Microsoft\VC\v170\Platforms\x64\PlatformToolsets\{v143, ClangCL, ...}
    vs_root = msbuild.parents[3]
    found = []
    for vc in sorted((vs_root / "MSBuild" / "Microsoft" / "VC").glob("v*")):
        pts = vc / "Platforms" / "x64" / "PlatformToolsets"
        if pts.is_dir():
            found += [p.name for p in pts.iterdir() if p.is_dir()]
    return sorted(set(found))


def choose_toolset(vcxproj, have, override=None):
    """The toolset a project asks for if installed, else the newest installed MSVC
    one (vNNN). ClangCL is kept when installed since it is a different compiler."""
    import re

    m = re.search(
        r"<PlatformToolset>([A-Za-z0-9]+)</PlatformToolset>",
        vcxproj.read_text(encoding="utf-8"),
    )
    asked = m.group(1) if m else "?"
    if override:
        return asked, override
    if asked in have:
        return asked, asked
    msvc = [t for t in have if re.fullmatch(r"v\d+", t)]
    if not msvc:
        die(
            "no MSVC toolset found; install 'Desktop development with C++' in Build Tools"
        )
    return asked, msvc[-1]


# Story-tab interpreters: (project dir under <ide>/Interpreters, repo URL, clone target
# relative to <ide>'s parent). The vcxproj files use ..\..\..\<Name> paths.
IDE_INTERPRETERS = [
    ("Frotz", "https://github.com/DavidKinder/Windows-Frotz.git", "Frotz", "Generic"),
    (
        "Glulxe",
        "https://github.com/DavidKinder/Glulxe.git",
        "Glulxe/Generic",
        "glulxe.h",
    ),
    ("Git", "https://github.com/DavidKinder/Git.git", "Git", "git.h"),
]


def cmd_ide_interpreters(work, plat, ide, toolset):
    if not IS_WINDOWS:
        die("the Windows IDE interpreters can only be built on Windows")
    ide = Path(ide) if ide else work / "Windows-Inform7"
    if not (ide / "Interpreters" / "Interpreters.sln").exists():
        die(f"no Windows IDE checkout at {ide}; pass --ide DIR")
    adv = ide.parent
    if not (adv / "Glk" / "Include" / "glk.h").exists():
        die("Glk helper repo missing; run `python build.py ide-libs` first")

    say("Interpreter source repos")
    for _, url, rel, marker in IDE_INTERPRETERS:
        clone_if_missing(url, adv / rel, marker)

    msbuild = find_msbuild()
    have = installed_toolsets(msbuild)
    say(f"MSBuild: {msbuild}")
    print(f"  installed toolsets: {', '.join(have)}")
    import re

    for proj, _, _, _ in IDE_INTERPRETERS:
        vcx = ide / "Interpreters" / proj / f"{proj}.vcxproj"
        asked, use = choose_toolset(vcx, have, toolset)
        # These projects are 32-bit (Release|Win32); read the platform rather than assume.
        plats = re.findall(
            r'ProjectConfiguration Include="Release\|([^"]+)"',
            vcx.read_text(encoding="utf-8"),
        )
        platform_name = plats[0] if plats else "Win32"
        say(f"Building {proj} (Release|{platform_name}; asks for {asked}, using {use})")
        run(
            [
                str(msbuild),
                "/m",
                "/nologo",
                "/v:minimal",
                "/p:Configuration=Release",
                f"/p:Platform={platform_name}",
                f"/p:PlatformToolset={use}",
                str(vcx),
            ],
            vcx.parent,
        )

    say("Result")
    out = ide / "Build" / "Interpreters"
    for name in ("frotz.exe", "glulxe.exe", "git.exe"):
        p = out / name
        print(
            f"  {name:12} {'%.1f MB' % (p.stat().st_size / 1e6) if p.exists() else 'MISSING'}"
        )


def cmd_ide(work, plat, ide, toolset):
    if not IS_WINDOWS:
        die("the Windows IDE can only be built on Windows")
    ide = Path(ide) if ide else work / "Windows-Inform7"
    sln = ide / "Inform7" / "Inform7.sln"
    if not sln.exists():
        die(f"no Windows IDE checkout at {ide}; pass --ide DIR")
    root = ide.parent.parent
    for needed in (
        root / "Libraries" / "libcef" / "Release" / "libcef.lib",
        root / "Libraries" / "jpeg" / "lib64" / "jpeg-static.lib",
        ide.parent / "Glk" / "Include" / "glk.h",
    ):
        if not needed.exists():
            die(f"{needed} missing; run `python build.py ide-libs` first")
    if not (ide / "Distribution" / "inform" / "inform7" / "Contents.w").exists():
        die(
            "Distribution/inform not present; run `python build.py integrate` first "
            "(the BuildDate pre-build step reads the Inform version from it)"
        )

    msbuild = find_msbuild()
    have = installed_toolsets(msbuild)
    project_toolset, toolset = choose_toolset(
        ide / "Inform7" / "Inform7.vcxproj", have, toolset
    )
    say(f"MSBuild: {msbuild}")
    print(
        f"  project asks for toolset {project_toolset}; installed: {', '.join(have)}; using {toolset}"
    )

    if toolset != project_toolset:
        say(f"Applying source compatibility patches for toolset {toolset}")
        apply_compat_patches(ide)

    props = [
        "/p:Configuration=Release",
        "/p:Platform=x64",
        f"/p:PlatformToolset={toolset}",
    ]
    common = [str(msbuild), "/m", "/nologo", "/v:minimal"] + props
    # The solution declares no dependency between its two projects, but Inform7's
    # pre-build step runs BuildDate.exe to write Build.h. Build it first, explicitly.
    say(
        "Building BuildDate (writes Inform7/Build.h from the Inform version in Distribution/inform)"
    )
    run(common + [str(ide / "BuildDate" / "BuildDate.vcxproj")], ide / "BuildDate")
    say(f"Building Inform7.exe (Release|x64, toolset {toolset})")
    run(common + [str(ide / "Inform7" / "Inform7.vcxproj")], ide / "Inform7")
    exe = ide / "Build" / "Inform.exe"  # the project's <ProjectName> is "Inform"
    if exe.exists():
        say(f"Built {exe}  ({exe.stat().st_size / 1e6:.1f} MB)")
        print(
            "Build\\ now also holds the CEF runtime files copied by the post-build step."
        )
        print(
            "Still from a released install if you want the Story tab: Build\\Interpreters\\*.exe"
        )
    else:
        die("MSBuild reported success but Build\\Inform.exe is missing")


def cmd_pins(work, plat):
    if not shutil.which("git"):
        die("git not found on PATH; pins needs git")
    # inweb re-tangles its tracked Tangled/inweb.c on every build; discard that
    # so the checkout is not blocked by it.
    git(work / "inweb", "checkout", "--", "Tangled/inweb.c")
    for name, ref in PINS.items():
        need_repo(work, name)
        say(f"{name} -> {ref}")
        if git(work / name, "fetch", "-q", "origin") is None:
            print("   (fetch failed; using local objects)")
        if git(work / name, "checkout", "-q", "--detach", ref) is None:
            die(f"could not check out {ref} in {name}")
        print(
            "   now at "
            + (
                git(work / name, "log", "-1", "--format=%h %ad %s", "--date=short")
                or "?"
            )
        )
    print(
        "\nNow rebuild from scratch: python build.py inweb --first && "
        "python build.py intest --first && python build.py inform --first"
    )


def cmd_doctor(work, plat):
    say("Builder")
    print(f"  build.py      {HERE}")
    print(f"  python        {sys.version.split()[0]}  ({sys.executable})")
    print(f"  platform      {plat}  ({platform.system()} {platform.machine()})")
    print(
        f"  git           {shutil.which('git') or 'not found (needed only to clone, and for pins)'}"
    )
    say("Toolchain")
    if IS_WINDOWS:
        if toolchain_present():
            print(
                "  "
                + version_of(
                    TOOLCHAIN / "llvm-mingw" / "bin" / "clang.exe", HERE, "--version"
                )
            )
            print(
                "  "
                + version_of(TOOLCHAIN / "make" / "bin" / "make.exe", HERE, "--version")
            )
            print(
                "  "
                + version_of(
                    TOOLCHAIN / "llvm-mingw" / "busybox" / "bin" / "busybox.exe",
                    HERE,
                    "--help",
                )
            )
        else:
            print("  not present: run `python build.py setup`")
    else:
        for t in ("clang", "make", "bash"):
            print(f"  {t:8} {shutil.which(t) or 'NOT FOUND'}")
    say(f"Sources in {work}")
    if not work.is_dir():
        print("  work folder does not exist")
        return
    for name, ref in PINS.items():
        repo = work / name
        if not repo.is_dir():
            print(
                f"  {name:8} MISSING  (git clone https://github.com/ganelson/{name}.git)"
            )
            continue
        head = (
            git(repo, "log", "-1", "--format=%h %ad", "--date=short")
            or "not a git checkout"
        )
        pinned = "at pin" if head.startswith(ref[:7]) else f"not at pin {ref}"
        if name == "inform":
            exe = repo / "inform7" / "Tangled" / f"inform7{EXE}"
        else:
            exe = repo / "Tangled" / f"{name}{EXE}"
        built = "built" if exe.exists() else "not built"
        print(f"  {name:8} {head:<22} {pinned:<24} {built}")


def cmd_env(work, plat, style):
    dirs = [str(d) for d in toolchain_dirs()]
    if not dirs:
        print("# Nothing to do on this platform: system clang and make are used.")
        return
    if style == "ps":
        print('$env:PATH = "' + ";".join(dirs) + ';" + $env:PATH')
        print(f'$env:INFORM_WORK = "{work}"')
    elif style == "cmd":
        print("set PATH=" + ";".join(dirs) + ";%PATH%")
        print(f"set INFORM_WORK={work}")
    else:
        posix = [d.replace("\\", "/") for d in dirs]
        print('export PATH="' + ":".join(posix) + ':$PATH"')
        print('export INFORM_WORK="' + str(work).replace("\\", "/") + '"')


def cmd_shell(work, plat, posix):
    need_toolchain()
    env = build_env()
    env["INFORM_WORK"] = str(work)
    cwd = str(work) if work.is_dir() else str(HERE)
    if IS_WINDOWS and not posix:
        shell = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/k",
            f"echo Inform builder shell: clang, make and sh are on PATH. && cd /d {cwd}",
        ]
    elif IS_WINDOWS:
        shell = [tool("bash")]
        print("Inform builder shell (busybox sh): clang, make and sh are on PATH.")
    else:
        shell = [os.environ.get("SHELL", "/bin/sh")]
        print("Inform builder shell: using system clang and make.")
    sys.exit(subprocess.call(shell, cwd=cwd, env=env))


def cmd_all(work, plat):
    cmd_setup(work, plat)
    cmd_inweb(work, plat, False)
    cmd_intest(work, plat, False)
    cmd_inform(work, plat, False)
    cmd_test(work, plat, "Acidity")


# --- Entry point ------------------------------------------------------------


def main(argv):
    args = list(argv)
    work = Path(os.environ.get("INFORM_WORK", HERE.parent / "_informing"))
    plat = None
    first = False
    style = "posix"
    posix_shell = False
    ide = None
    toolset = None
    app = out = name = bundle_id = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--work":
            i += 1
            work = Path(args[i])
        elif a == "--platform":
            i += 1
            plat = args[i]
        elif a == "--ide":
            i += 1
            ide = args[i]
        elif a == "--toolset":
            i += 1
            toolset = args[i]
        elif a == "--app":
            i += 1
            app = args[i]
        elif a == "--out":
            i += 1
            out = args[i]
        elif a == "--name":
            i += 1
            name = args[i]
        elif a == "--bundle-id":
            i += 1
            bundle_id = args[i]
        elif a == "--first":
            first = True
        elif a == "--ps":
            style = "ps"
        elif a == "--cmd":
            style = "cmd"
        elif a == "--posix":
            posix_shell = True
        elif a in ("-h", "--help", "help"):
            print(__doc__)
            return 0
        else:
            rest.append(a)
        i += 1
    work = work.resolve()
    plat = plat or detect_platform()
    if not rest:
        print(__doc__)
        return 2
    cmd, params = rest[0], rest[1:]

    if cmd == "doctor":
        cmd_doctor(work, plat)
    elif cmd == "setup":
        cmd_setup(work, plat)
    elif cmd == "pins":
        cmd_pins(work, plat)
    elif cmd == "inweb":
        cmd_inweb(work, plat, first)
    elif cmd == "intest":
        cmd_intest(work, plat, first)
    elif cmd == "inform":
        cmd_inform(work, plat, first)
    elif cmd == "all":
        cmd_all(work, plat)
    elif cmd == "test":
        cmd_test(work, plat, params[0] if params else "Acidity")
    elif cmd == "integrate":
        cmd_integrate(work, plat, ide)
    elif cmd == "mac-integrate":
        cmd_mac_integrate(work, plat, app, out, name, bundle_id)
    elif cmd == "ide-libs":
        cmd_ide_libs(work, plat, ide)
    elif cmd == "ide":
        cmd_ide(work, plat, ide, toolset)
    elif cmd == "ide-interpreters":
        cmd_ide_interpreters(work, plat, ide, toolset)
    elif cmd == "shell":
        cmd_shell(work, plat, posix_shell)
    elif cmd == "env":
        cmd_env(work, plat, style)
    else:
        die(f"unknown command '{cmd}'. Try: python build.py help")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
