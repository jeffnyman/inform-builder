# Inform Easy Builder

One Python script that compiles the Inform 7 ecosystem — **inweb**, **intest**
and the core **inform** tools (inform7, inbuild, inter, inblorb, inform6,
inpolicy) — from source, on Windows, Linux or macOS. On Windows it can also
feed that build into the **Windows Inform 7 IDE** and compile the IDE itself
with the free Visual Studio Build Tools. On macOS it can make a copy of the
official **Mac Inform app** that runs the build, with no Xcode needed.

The core tools build **without installing anything**: no MSYS2, no Cygwin, no
WSL, no Visual Studio, not even Git for Windows. A portable toolchain is
downloaded into this folder, and deleting the folder removes every trace. The
resulting `.exe` files depend only on the Universal C Runtime that ships with
Windows 10 and 11.

```
python build.py all          # the command-line Inform tools
python build.py integrate    # put them into a Windows-Inform7 checkout
python build.py ide-libs     # fetch the IDE's third-party libraries
python build.py ide          # compile Inform.exe with VS Build Tools
python build.py ide-interpreters   # and the Story-tab interpreters
python build.py mac-integrate      # macOS: a copy of Inform.app running them
```

## How it works

The upstream projects document only an MSYS2 route for Windows. Their makefiles
need three things: a `clang` that targets Windows and accepts GNU-style flags, a
GNU `make`, and a POSIX `sh` with `cp`, `rm` and `mkdir` for the recipes. Instead
of MSYS2, this builder uses two zip releases:

| Piece | Provides | Size unpacked | Source |
|---|---|---|---|
| `toolchain/llvm-mingw/` | clang, lld, mingw-w64 UCRT sysroot, **and a bundled busybox** with `sh`, `bash`, `cp`, `rm`, `mkdir` and 170 other applets | ~735 MB | https://github.com/mstorsjo/llvm-mingw |
| `toolchain/make/` | GNU Make 4.4.1 as a single exe | ~1 MB | https://sourceforge.net/projects/ezwinports/ |

llvm-mingw's clang defaults to the `x86_64-w64-windows-gnu` target and accepts
inweb's flags unchanged, and its busybox provides the shell. So **no upstream
file is modified**; `build.py` only puts these on PATH and runs the upstream
`first.sh` scripts and makefiles exactly as their READMEs describe.

On Linux and macOS no toolchain is downloaded. The system `clang`, `make` and
`bash` are used and the matching inweb platform name is detected automatically.

## Prerequisites

- **Python 3.8 or later.** Nothing from PyPI.
- **git**, to clone the three source repositories and for the `pins` command.
  Not needed for building.
- Windows 10/11 64-bit, or Linux/macOS with `clang` and `make` installed.
- About 1.5 GB of disk on Windows: toolchain plus sources. Internet access for
  the one-time toolchain download (~190 MB).
- Only for compiling the Windows IDE (`ide` command): Visual Studio Build Tools
  2022 or 2026 with MFC, plus about 1.5 GB more for libraries. See
  "Compiling the IDE itself" below.
- Only for `mac-integrate`: the official Mac Inform app installed, normally at
  `/Applications/Inform.app`. The Xcode command-line tools are enough; full
  Xcode is not needed.

## Layout

```
<somewhere>\
  inform-builder\          <- this folder
    build.py               <- builds everything
    inform.py              <- runs what was built (compile, play, ide, ...)
    README.md
    toolchain\             <- created by `setup`; never commit it
  _informing\              <- the sources, as siblings with exactly these names
    inweb\                 git clone https://github.com/ganelson/inweb.git
    intest\                git clone https://github.com/ganelson/intest.git
    inform\                git clone https://github.com/ganelson/inform.git
```

The sources folder defaults to `../_informing` beside this folder. Point
elsewhere with `--work DIR` or the `INFORM_WORK` environment variable. The
three repos must be siblings with those names, because the upstream makefiles
refer to `../inweb/Tangled/inweb` and so on.

## Quick start

```
cd inform-builder
python build.py pins        # clones the three repos into ../_informing, at verified commits
python build.py all         # setup + inweb + intest + inform + smoke test
```

`pins` creates the sources folder and clones whichever of the three repos are
missing, then checks all three out at the combination recorded in `build.py`
(see "Matching versions" below). To track upstream `master` instead, clone
them yourself:

```
git clone https://github.com/ganelson/inweb.git  _informing/inweb
git clone https://github.com/ganelson/intest.git _informing/intest
git clone https://github.com/ganelson/inform.git _informing/inform
```

Or step by step:

| Command | What it does | Time* |
|---|---|---|
| `python build.py doctor` | Checks prerequisites; shows toolchain versions and repo states | instant |
| `python build.py setup` | Downloads and unpacks the toolchain on Windows (idempotent); on Linux and macOS, checks that `clang` and `make` are installed | download-bound |
| `python build.py pins` | Clones any of the three repos that are missing, then checks them out at the verified commit combination | seconds; about a minute if cloning |
| `python build.py inweb` | Builds inweb | 25 s |
| `python build.py intest` | Builds intest | 15 s |
| `python build.py inform` | Builds all core Inform tools and the test interpreters | 3.5 min |
| `python build.py test` | Compiles and plays the "Acidity" test case via intest | 2 s |
| `python build.py test all` | The full suite, about 2500 cases | 5 min to 2 h |
| `python build.py integrate` | Windows: copies tools and resources into a Windows IDE checkout; see below | 3.5 min |
| `python build.py mac-integrate` | macOS: makes a renamed, re-signed copy of `Inform.app` that runs this build; see below | 6 s |
| `python build.py ide-libs` | Windows: fetches the IDE's third-party libraries and helper repos; see below | download-bound |
| `python build.py ide` | Windows: compiles `Inform.exe` with MSBuild from Visual Studio Build Tools | 4 min |
| `python build.py ide-interpreters` | Windows: clones Frotz, Glulxe and Git and builds the Story-tab interpreters | 1 min |
| `python build.py shell` | Opens a shell in the sources folder with `INFORM_WORK` set, and on Windows the toolchain on PATH | |
| `python build.py env` | Prints lines that set `INFORM_WORK`, and on Windows put the toolchain on PATH, for your shell (`--ps`, `--cmd`, or POSIX). On macOS and Linux: `eval "$(python build.py env)"` | |

\* Measured on a desktop PC, 2 October 2026.

The first run of each build uses the upstream `first.sh` bootstrap; later runs
are an incremental `make`. Add `--first` to force a from-scratch bootstrap, for
example after `git pull` changes the makescripts or after `pins`.

### Output

Executables land where upstream puts them, inside each source tree:

| Tool | Executable |
|---|---|
| inweb | `inweb/Tangled/inweb.exe` |
| intest | `intest/Tangled/intest.exe` |
| inform7 | `inform/inform7/Tangled/inform7.exe` |
| inbuild | `inform/inbuild/Tangled/inbuild.exe` |
| inter | `inform/inter/Tangled/inter.exe` |
| inblorb | `inform/inblorb/Tangled/inblorb.exe` |
| inform6 | `inform/inform6/Tangled/inform6.exe` |
| inpolicy | `inform/inpolicy/Tangled/inpolicy.exe` |
| dumb-frotz, glulxe (test interpreters) | `inform/inform6/Tests/Assistants/.../*.exe` |

### Working by hand

`python build.py shell` opens a prompt with `clang`, `make` and `sh` on PATH, so
everything in the upstream build documentation works unchanged:

```
make -f inweb/inweb.mk
cd inform
make check
..\intest\Tangled\intest inform7 -show Acidity
```

Pass `--posix` for the busybox shell instead of cmd.exe. Or paste the output of
`python build.py env --ps` into PowerShell.

## Using what you built: `inform.py`

Once things are built, `inform.py` is the front door, so nobody has to remember
where the executables live or what flags they want:

| Command | What it does |
|---|---|
| `python inform.py where` | Shows which copy of each tool and which Internal folder will be used |
| `python inform.py ide` | Launches the IDE, detached: `Build\Inform.exe` on Windows, the `mac-integrate` app on macOS. Files given after it, such as a `.inform` project, are opened in it |
| `python inform.py compile My.inform` | inform7 then inform6, exactly as the IDE does; output in `My.inform\Build\output.ulx`. `--z8` for the Z-machine, `--release` for a release build (and a Blorb if `Release.blurb` exists) |
| `python inform.py play story.ulx` | Plays a story in the dumb-terminal glulxe or frotz (chosen by extension) |
| `python inform.py inform7 ...` | Pass-through to inform7, inbuild, inform6, inblorb, intest or inweb. For inform7 and inbuild, `-internal` is filled in for you |

It prefers the integrated set in `Windows-Inform7\Build\Compilers` with
`Build\Internal` beside it, which is the pairing the IDE uses, and otherwise
falls back to the `Tangled\` copies with `inform\inform7\Internal`. It never
mixes the two; `where` tells you which is active, and `--from-source` forces
the second. A bare project folder with only `Source\story.ni` works: `compile`
creates the `uuid.txt` that inform7 requires, as the IDE would have.

## Matching versions: read this before `git pull`

The three repositories are developed together but released separately, and
**upstream `master` of inform does not always compile against upstream `master`
of inweb.** On 2 October 2026 it did not: inweb's newest commit (705085d7,
28 September, "Substantial refactor of the rendering engine") removed
`Markdown::render_extended`, which inform 10.2.0-beta+6Y13 (24 June) still
calls from inbuild. The symptom is nine errors like

```
error: call to undeclared function 'Markdown__render_extended'
```

while compiling inform7. `build.py` recognises this pattern and says so.

`build.py` records a combination verified to build and pass tests together, and
`python build.py pins` checks all three repos out at those commits (detached
HEAD; `git checkout master` inside a repo returns it to the tip). If you pull
newer sources and inform7 fails with undeclared `Markdown__*` or other
foundation-module functions, that is version skew, not a toolchain fault: move
inweb back to a commit dated before inform's most recent commit, or forward to
one after inform has caught up, and rebuild with `--first`.

| Repo | Pinned commit | Version |
|---|---|---|
| inweb | `e5329237` (21 Aug 2026) | 9.0-beta+1C30 |
| intest | `00857f4` (24 Apr 2026) | 2.2.0-beta+1A76 |
| inform | `5c7ba42b7` (24 Jun 2026) | 10.2.0-beta+6Y13, upstream master |

Pins and toolchain versions live at the top of `build.py` and can be overridden
with environment variables of the same names (`INWEB_REF`, `LLVM_MINGW_TAG`, ...).

## Status

Everything below was verified on Windows 11 on 2 October 2026 with Git for
Windows removed from PATH, so only Python and the downloaded toolchain were used.

| Step | Result |
|---|---|
| Toolchain download and unpack | OK |
| inweb 1C30: bootstrap and self-rebuild | OK, 25 s |
| intest 1A76 | OK, 15 s |
| inform 10.2.0-beta+6Y13: all tools and test interpreters | OK, 3 min 34 s |
| `test` (Acidity: inform7 → inform6 → dumb-frotz → transcript compare) | Passed |
| `integrate` into a Windows-Inform7 checkout | OK, 3 min 30 s: 7 exes, 293 Internal files, 1433 Documentation files |
| A project compiled and played using only `Build\Compilers` and `Build\Internal` | Passed; banner shows Inform 7 v10.2.0 |
| `ide-libs`: 9 libraries + 2 helper repos fetched and laid out | OK |
| `ide`: `Inform.exe` compiled with **VS 2022 Build Tools**, toolset v143 | OK, 6.1 MB, 0 errors (one guarded source patch, see below) |
| `ide-interpreters`: frotz, glulxe (v143) and git (clang-cl), 32-bit | OK, 0 errors |
| `Inform.exe` launched from `Build\` | Opens the "Welcome to Inform" launcher with no missing-component warning; CEF helper processes start |
| `inform.py`: `where`, `ide`, `compile` (Glulx; Z-machine release with Blorb), `play` both, pass-through | All verified |
| `test all` (full suite) | Not yet run |
| Linux paths in `build.py` | Written, not yet exercised |
| `Build\Retrospective\` (legacy compilers for very old projects) | Not available from source; optional |

On macOS 26.6 (Apple Silicon, Xcode command-line tools only, no full Xcode),
2 October 2026:

| Step | Result |
|---|---|
| `pins`, then `all` (inweb, intest, inform with Apple clang and make 3.81) | OK, 62 s; Acidity passed |
| `mac-integrate` from the official Inform.app 1.82 | OK, 6 s: 7 tools, 293 Internal files, 1134 documentation pages; `codesign --verify --deep --strict` passes |
| A project compiled and played with only the tools and `Internal` inside the new app | Passed; banner shows Inform 7 v10.2.0 |
| The new app launched and used through its GUI | Worked in a hands-on check; no problems seen |

## Feeding the build into the Windows IDE

The Windows IDE (https://github.com/DavidKinder/Windows-Inform7) does not
compile the Inform tools itself. At run time `Inform7.exe` launches
`<AppDir>\Compilers\inform7.exe -internal <AppDir>\Internal ...`, so whatever
sits in `Build\Compilers` and `Build\Internal` is the Inform it uses. Upstream
already provides the plumbing: if `inform` is checked out at
`Windows-Inform7/Distribution/inform`, its makefile picks up
`Distribution/make-integration-settings.mk` and `make forceintegration` copies
everything into `Build\`. The IDE's own `.gitignore` expects exactly that layout.

`python build.py integrate` automates it:

1. Creates directory junctions `Distribution\inweb`, `Distribution\intest` and
   `Distribution\inform` pointing at your source checkouts, so nothing is moved
   or duplicated. (Existing folders are left alone.)
2. Runs `make` in `Distribution\inform` so the integration settings are active.
3. Copies inform7, inbuild, inform6, inblorb, intest and the dumb-terminal frotz
   and glulxe into `Build\Compilers` **with `.exe` extensions**. The upstream
   makefile does this with `cp inform7/Tangled/inform7 ...`, relying on
   Cygwin/MSYS2's implicit `.exe` handling, which busybox does not have. This is
   the one place `build.py` does the makefile's job itself.
4. Runs the remaining upstream `forcetransfer*` targets, which populate
   `Build\Internal` (extensions, kits, templates, Preform syntax) and
   `Build\Documentation` (manuals, advice pages, outcome pages, images) via
   `inbuild`.

Pass `--ide DIR` if the IDE checkout is not at `<work>/Windows-Inform7`.

To check the result by hand, mimic the IDE's command lines against a project
(a real project folder needs a `uuid.txt`; the IDE creates one):

```
Build\Compilers\inform7 -internal Build\Internal -project My.inform -format=Inform6/32d
cd My.inform\Build
..\..\Build\Compilers\inform6 -E1SDwG +include_path=..\Source,.\ auto.inf output.ulx
..\..\Build\Compilers\glulxe output.ulx
```

## Compiling the IDE itself (`Inform.exe`) with Visual Studio Build Tools

The IDE README asks for Visual Studio 2026 Community. You do not need the full
IDE, and you do not need the 2026 version. **Visual Studio Build Tools**, the
free command-line-only package, is enough, and the 2022 edition works with one
guarded source patch that `build.py` applies for you.

### Prerequisites

Install [Build Tools for Visual Studio](https://visualstudio.microsoft.com/downloads/)
(listed under "Tools for Visual Studio"; Microsoft publishes a 2026 edition as
well as 2022) with the workload **Desktop development with C++** and these
individual components:

- C++ MFC for latest build tools (x86 & x64)
- Windows 11 SDK (any 10.0.x)
- C++ Clang Compiler for Windows and MSBuild support for LLVM (clang-cl) —
  needed for the Git interpreter (`ide-interpreters`), not for `Inform.exe`

This is the one system-wide install in the whole process, and it is
Microsoft's own compiler; there is no portable equivalent for MFC.

### Layout

The IDE's project files use fixed relative paths, so the folders must sit like
this (David Kinder's `<root>\Adv\Inform7` layout, with our `_informing` playing
the role of `Adv`):

```
<root>\                       e.g. F:\Projects
  Libraries\                  <- `ide-libs` creates this: David Kinder's Libraries repo
    mfc\  libmodplug\         (from that repo) plus the downloads below
    zlib\ libpng\ jpeg\ libogg\ libvorbis\ minimp3\ hunspell\ json\ libcef\
  _informing\                 <- your sources folder
    Windows-Inform7\          <- the IDE checkout
    Glk\                      <- `ide-libs` clones David Kinder's Windows-Glk here
    Frotz\  Git\  Glulxe\Generic\   <- `ide-interpreters` clones these
    inweb\  intest\  inform\
```

### Steps

```
python build.py integrate    # Build\Compilers and Build\Internal; also needed by the BuildDate pre-build step
python build.py ide-libs     # ~350 MB of downloads, see table
python build.py ide          # MSBuild Release|x64 -> Build\Inform.exe
```

`ide-libs` fetches these, pinned in `build.py` and overridable by environment
variable:

| Library | Version | Notes |
|---|---|---|
| zlib | 1.3.2 | source |
| libpng | 1.6.59 | source; `pnglibconf.h` generated from the prebuilt one minus `PNG_WRITE_*`, `PNG_SAVE_*`, `PNG_SIMPLIFIED_WRITE_*` as the IDE README instructs |
| libjpeg-turbo | 3.2.0 | the prebuilt VC x64 package is an NSIS installer; it is **opened with 7-Zip, not run**, so nothing is registered with Windows. A portable `7z.exe` is pulled out of 7-Zip's own self-extracting archive for this. `lib` is renamed `lib64` |
| libogg / libvorbis | 1.3.6 / 1.3.7 | source |
| minimp3 | master | header-only |
| hunspell | **1.7.3** | 1.7.4 (Sep 2026) added `hunspelltrace.cxx`, which the IDE project does not compile, so it fails to link. Stay on 1.7.3 until the IDE catches up |
| nlohmann json | 3.12.0 | `include.zip` |
| CEF | 144.0.12 minimal | 151 MB; the exact build the IDE was developed against. Its `libcef_dll` wrapper (171 files) is compiled into Inform.exe |

`ide` then:

1. Locates MSBuild with `vswhere` and lists the installed MSVC toolsets.
2. Uses the toolset the project asks for (`v145`) if present, otherwise the
   newest installed one (`v143` for Build Tools 2022). Override with
   `--toolset NAME`.
3. If the toolset differs from the project's, applies the compatibility patches
   listed in `IDE_COMPAT_PATCHES`. Today that is one: `FindAllHelper.cpp` names
   `std::regex_constants::_Error_syntax`, an MSVC-internal code that first
   appears in the VS 2026 STL. It is wrapped in
   `#if _MSVC_STL_VERSION >= 145`. The patch is idempotent and shows up as a
   3-line `git diff` in the IDE checkout; `git checkout Inform7/FindAllHelper.cpp`
   reverts it.
4. Builds `BuildDate.vcxproj` first (it writes `Inform7/Build.h` with the date
   and the Inform version read from `Distribution/inform`), then
   `Inform7.vcxproj`. The solution file declares no order between them, so
   building the `.sln` with `/m` can race.
5. The project's own post-build step copies the CEF runtime (`libcef.dll`,
   `.pak` files, `icudtl.dat`, ...) into `Build\`.

The output is `Build\Inform.exe` (the project is named Inform7 but its
`<ProjectName>` is `Inform`), about 6 MB, statically linked against MFC.

### The Story-tab interpreters

```
python build.py ide-interpreters
```

clones David Kinder's Windows-Frotz, Glulxe and Git repos to `_informing\Frotz`,
`_informing\Glulxe\Generic` and `_informing\Git` (the paths the project files
expect), then builds `Interpreters\Frotz`, `Glulxe` and `Git` into
`Build\Interpreters\`. Notes:

- These are **32-bit** projects (`Release|Win32`), unlike the IDE. Build Tools
  installs the x86 compiler with the C++ workload, so nothing extra is needed.
- Frotz and Glulxe ask for `v145` and fall back to the installed MSVC toolset
  the same way `ide` does. Git asks for `ClangCL`, which Build Tools provides
  when the Clang components are selected, and is built with it as-is.
- The IDE checks for these three files at startup; with them present it opens
  straight to the "Welcome to Inform" launcher.

### Still not from source

`Build\Retrospective\` holds the bundled older compilers (6L02, 6L38 and so on)
for opening very old projects. They are only available from an installed
release of Windows Inform 7. Optional: without them the IDE simply cannot offer
those legacy versions in a project's settings.

## Feeding the build into the Mac app (`mac-integrate`)

Building the Mac IDE from source (https://github.com/TobyLobster/Inform) needs
full Xcode, a signing setup, and an "Inform Core" folder layout with a private
makefile that its build script expects but the repository does not include.
None of that is needed to *run* a new compiler in the Mac IDE, because the app
finds its tools by name:

- `Contents/MacOS/ni` is inform7 (under its old name), `cBlorb` is inblorb, and
  `inform6` and `intest` keep their names.
- `Contents/Resources/Internal` is passed to `ni` with `-internal`.
- The documentation pages live in `Contents/Resources/en.lproj`.

So a copy of the official app with those swapped is a Mac IDE running your
build:

```
python build.py all
python build.py mac-integrate
open ~/Applications/"Inform 10.2.app"
```

`mac-integrate`:

1. Copies `/Applications/Inform.app` (or `--app PATH`) into a temporary folder,
   without its extended attributes.
2. Deletes the copy's `Internal` folder and its HTML documentation pages. The
   official 1.82 app's kits are for Inform 10.1, and if they are left in place
   10.2 fails with "'Web Syntax Version' has been withdrawn". The app's own
   `.strings` and `.nib` files are kept.
3. Writes a `make-integration-settings.mk` beside `inform/` for the Mac layout
   and runs upstream's `make forceintegration`, then removes the file again so
   it does not affect later builds. It refuses to run if a settings file it did
   not write is already there. The staging copy is used because upstream's
   settings cannot contain paths with spaces.
4. Renames the app (`--name`, default `Inform <major>.<minor>` from the built
   inform7, for example "Inform 10.2") and gives it its own bundle identifier
   (`--bundle-id`, default `com.inform7.inform-compiler.source-build`). That
   keeps its preferences separate and lets you choose which app opens
   `.inform` files.
5. Signs the whole bundle ad hoc. Swapping files breaks Apple's signature, and
   macOS kills a binary inside a bundle with a broken seal (exit code 137). An
   ad hoc signature needs no Apple developer account and is valid on this Mac
   only.
6. Moves it to `--out DIR`, default `~/Applications`. A previous
   `mac-integrate` build at that path is replaced; any other app there is left
   alone and the command stops.

Leave the official app installed: it is the source of the copy, and your
fallback. Things to know when running both:

- Both read `~/Library/Inform`, so an extension installed from one is seen by
  the other. The path is fixed in the app, so back that folder up if you want
  to try 10.2 extensions without risk to your 10.1 setup.
- A project compiled under 10.2 may have its settings updated in a way the
  official 10.1 app does not expect.
- The GUI is still Inform.app 1.82, written for Inform 10.1.2. Compiling
  through it is expected to work. Panels that read `Internal` directly
  (extensions, index, documentation) are the most likely places for rough
  edges.
- The legacy compilers in `Contents/MacOS/6L02`, `6L38` and `6M62` are kept
  from the official app unchanged.

## Troubleshooting

**`python` opens the Microsoft Store or is not found.** Install Python from
https://www.python.org/ and tick "Add to PATH", or run `py build.py ...` if you
have the Windows launcher.

**inform7 fails with `undeclared function 'Markdown__...'`.** Version skew. See
"Matching versions" above; run `python build.py pins`, then rebuild with
`--first`.

**A different `clang`, `make` or `sh` is being used.** `build.py` prepends the
toolchain to PATH for every command it runs, so this should not happen from
`build.py` itself. If you set PATH by hand, keep the order the `env` command
prints: GNU make must come before busybox, because busybox has its own
non-GNU `make`.

**Antivirus slows or quarantines the build.** Freshly linked `.exe` files in
`Tangled/` folders sometimes trip real-time scanners. Excluding the sources
folder from scanning fixes it.

**`git status` shows `Tangled/inweb.c` modified.** Expected. Inweb re-tangles
its own C source on every build. Don't commit it unless you changed inweb.

**Updating the toolchain.** Change `LLVM_MINGW_TAG` at the top of `build.py`,
delete `toolchain/llvm-mingw`, run `python build.py setup`. The
`toolchain/downloads` folder is only a cache and can be deleted at any time.

**`mac-integrate` cannot replace the previous app: "Operation not
permitted".** macOS App Management protection. Give your terminal App
Management access in System Settings > Privacy & Security, or delete the old
app in Finder and run the command again.

## Uninstall

Delete the `inform-builder` folder. That is all. On macOS, also delete the
app `mac-integrate` made (by default `~/Applications/Inform 10.2.app`).
