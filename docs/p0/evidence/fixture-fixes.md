# P0 Fixture Fix Log

Every change made to a fixture after the corpus was first swept, with the exact
pre-fix failure it corrects and the root cause. All pre-fix lines are copied
verbatim from `fpc-host-prefix.txt` (host FPC 3.2.2, i386-Win32) unless another
evidence file is named.

> **Note on paths in this log.** Fixture paths are quoted as they stood *at the
> time of the fix*, because that is what the pre-fix evidence line contains.
> Paths that name a file since renamed — `corpus/dialects/delphi/delphi_classes.pas`
> (§1) and `corpus/language/nested_routines.pas` (§4) — deliberately do **not**
> resolve on disk today; the files now live at `DelphiClasses.pas` and
> `NestedRoutines.pas`. Every other path in this log resolves.

## Why these edits are legitimate

`corpus/README.md` forbids editing a fixture **to make a tool pass**. These
edits do the opposite: each corrected a defect in the fixture *authoring* so the
file is valid Pascal that the tool correctly demanded. The tools were never
weakened, and no fixture's asserted behavior was relaxed to accommodate a
compiler or parser. Where a fixture is *supposed* to fail (missing platform
units), it still fails and is still marked `FAIL-DEPENDENCY`.

Rule applied: an edit is allowed only when (a) the pre-fix source is invalid
Pascal under the language rules, or (b) the unit name and file name disagree,
or (c) a header comment states an expectation that the file itself contradicts.

---

## 1. `corpus/dialects/delphi/delphi_classes.pas` — two defects, two edits

### 1a. Header comment reword

Pre-fix (FPC host, `-Mdelphi`):

```
FAIL|delphi|dialects\delphi\delphi_classes.pas|delphi_classes.pas(1,69) Fatal: Syntax error, "BEGIN" expected but "identifier UNDER" found
```

**Root cause.** The header contained a compiler directive inside a brace
comment: `... Delphi/Object Pascal ({$mode delphi} under FPC). ...`. Under
`-Mdelphi`, nested `{$...}` inside `{...}` does not nest — the `}` of the inner
directive *closes* the outer comment, so the trailing words `under FPC). ...`
become live source and the parser dies at `identifier UNDER`. Probe `P17` in
`probes.txt` reproduces this in isolation (directive nested in a brace comment
is fatal under `-Mdelphi`); probe `P16` shows the same construct only warns
under `-Mfpc`, which is why this defect hid until the file was compiled in the
mode its own header claimed.

**Fix.** Header reworded to `Delphi/Object Pascal.` — no directive inside a
comment. Source semantics unchanged.

### 1b. File renamed `delphi_classes.pas` → `DelphiClasses.pas`

The header defect above masked a second one: compilation aborted at line 1
before reaching line 3, so the unit-name check never ran. Probe `F1` (isolated
repro) showed:

```
delphi_classes.pas(1,19) Error: Illegal unit name: DelphiClasses (expecting PROGRAM)
```

**Root cause.** FPC requires `unit X` to live in `X.pas`. The fixture declared
`unit DelphiClasses` in `delphi_classes.pas`. This is also the cause of the
cascade failure in `fpc-host-prefix.txt`:

```
FAIL|delphi|applications\project_files\delphi_style_app.dpr|delphi_style_app.dpr(6,13) Fatal: Can't find unit DelphiClasses used by DelphiStyleApp
```

because `uses DelphiClasses` searches for `DelphiClasses.pas`, not
`delphi_classes.pas`.

**Fix.** Renamed the *file*, not the unit, so the idiomatic `unit DelphiClasses`
and the `uses DelphiClasses` clause in the `.dpr` both stay unchanged. This
matches the corpus convention already used by `uMath.pas`, `uReport.pas`,
`uMainForm.pas` (file name = unit name). The `.dproj` and `.dpk` path
references were updated in the same change. Program names need not match file
names (probe `P14`), so no `.dpr`/`.lpr` renames were needed.

---

## 2. `corpus/dialects/fpc/mode_objfpc.pas` — header comment reword

**Root cause.** Same class as 1a: the header read `Free Pascal, {$mode objfpc}
with class type`, nesting a directive in a brace comment. Host FPC only
*warned* under `-Mobjfpc` (probe `P16`), so `fpc-host-prefix.txt` shows
`PASS|objfpc|dialects\fpc\mode_objfpc.pas` — but the header still states a false
expectation, and the same construct is a hard error under `-Mdelphi` (probe
`P17`). Both parser evaluations rejected it, so it was corrected on the
authority of the language rule, not to flip a test result: a comment must not
contain an unbalanced directive.

**Fix.** Header reworded to `Free Pascal mode objfpc, with class type.`

---

## 3. `corpus/language/variant_record.pas` — `ShortString[31]` → `string[31]`

Pre-fix:

```
FAIL|fpc|language\variant_record.pas|variant_record.pas(9,36) Error: Error in type definition
```

**Root cause.** `ShortString[31]` is not a valid type declaration. The
length-suffixed short-string type is written `string[31]`; `ShortString` is the
fixed 255-byte type and takes no suffix. Probe `P15` confirms `string[31]`
compiles in `-Mfpc`.

**Fix.** `1: (StrValue: ShortString[31]);` → `1: (StrValue: string[31]);`. The
fixture's stated intent (short-string field with a 31-char bound in a variant
record) is preserved exactly.

---

## 4. `corpus/language/nested_routines.pas` → `NestedRoutines.pas`

Pre-fix:

```
FAIL|delphi|language\nested_routines.pas|nested_routines.pas(3,20) Error: Illegal unit name: NestedRoutines (expecting PROGRAM)
```

**Root cause.** Same unit-name/file-name rule as 1b. Nothing references this
unit, so the rename is a pure file-name correction; the `unit NestedRoutines`
declaration is unchanged. Probe `F2` confirms `unit NestedRoutines` in
`NestedRoutines.pas` compiles under `-Mdelphi`.

---

## 5. `corpus/language/exception_flow.pas` — added `uses SysUtils;`

Pre-fix:

```
FAIL|objfpc|language\exception_flow.pas|exception_flow.pas(6,30) Error: Identifier not found "Exception"
```

**Root cause.** The fixture raises and catches `class(Exception)` and reads
`E.Message`, but never imports the unit that declares `Exception`. `Exception`
and `Message` live in `SysUtils`, not `System`. The header already claimed
"compiles with FPC", so the fixture contradicted itself.

**Fix.** Added `uses SysUtils;` after the mode directive. No behavior change —
this is the import the fixture's own code required.

---

## 6. `corpus/language/file_io.pas` — added `{$mode objfpc}`

Pre-fix:

```
FAIL|fpc|language\file_io.pas|file_io.pas(15,3) Error: Identifier not found "AssignFile"
```

**Root cause.** The fixture used `AssignFile`/`CloseFile` while carrying no
`{$mode}` directive, so it compiled in FPC's default `-Mfpc` mode. Probes
`P06`–`P11` and the ppu scan in `probes.txt` pin the mechanism exactly:

| probe | result |
|---|---|
| `P06` bare `AssignFile` in `-Mfpc` | FAIL `Identifier not found "AssignFile"` |
| `P07` bare `AssignFile` in `-Mobjfpc` | PASS |
| `P08` bare `AssignFile` in `-Mdelphi` | PASS |
| `P09` `uses ObjPas` restores it in `-Mfpc` | PASS |
| `P10` `System.AssignFile` in `-Mfpc` | FAIL |
| `P11` `ObjPas.AssignFile` in `-Mobjfpc` (no `uses`) | PASS |

```
system.ppu|path=C:\FPC\3.2.2\units\i386-win32\rtl\system.ppu|AssignFile=False|CloseFile=False|Rewrite=True|Reset=True
objpas.ppu|path=C:\FPC\3.2.2\units\i386-win32\rtl\objpas.ppu|AssignFile=True|CloseFile=True|Rewrite=False|Reset=True
```

`AssignFile`/`CloseFile` are declared in **`ObjPas`**, not `System`.
`-Mobjfpc` and `-Mdelphi` pull `ObjPas` in automatically; `-Mfpc`/`-Mtp` do
not, which is exactly the observed mode split. The fixture needs the mode its
own API requires.

**Fix.** Added `{$mode objfpc}` on line 4. The code was correct; the mode
directive it depended on was missing.

---

## 7. `corpus/dbaccess/ado_style_connection.pas` — expectation documented

This fixture **passed** host FPC pre-fix (`PASS|fpc|dbaccess\ado_style_connection.pas`)
because Windows FPC ships the COM/`ComObj` units. Its header asserted
FAIL-DEPENDENCY unconditionally, which is wrong on this platform.

**Fix.** Header now states the platform-dependent expectation explicitly: it
compiles on Windows hosts, and is expected to fail as `FAIL-DEPENDENCY` on
Linux where `ComObj` is absent. No code change. The Linux side is checked
against the pinned Docker image (see `fpc-docker.txt`).

---

## 8. Project files — path references

Both project files reference the renamed unit; both were updated to
`DelphiClasses.pas` to follow fix 1b. No other content changed; these remain
`DISCOVERY-ONLY` fixtures and are never compiled in P0.

### 8b. `delphi_style_app.dproj` — relative-path depth corrected

Verified during the P0 finalization review (2026-11-13). Both files live in
`corpus/applications/project_files/` and the unit lives in
`corpus/dialects/delphi/`, so the correct reference is two directories up.

| file | reference as found | resolves to | exists |
|---|---|---|---|
| `legacy_pack.dpk` | `..\..\dialects\delphi\DelphiClasses.pas` | `corpus/dialects/delphi/DelphiClasses.pas` | yes |
| `delphi_style_app.dproj` | `..\dialects\delphi\DelphiClasses.pas` | `corpus/applications/dialects/delphi/DelphiClasses.pas` | **no** |

**Root cause.** The `.dproj` reference was one `..` short and pointed at a
directory that does not exist. It went unnoticed because `.dproj` is
`DISCOVERY-ONLY`: no P0 sweep resolves or compiles that path, so no tool ever
exercised it. The `.dpk` in the same directory was already correct, which is
what made the discrepancy detectable.

**Fix.** `..\dialects\...` → `..\..\dialects\...`, matching the `.dpk`. The
XML structure, `ProjectGuid`, `MainSource` and all other properties are
unchanged.

**Rule check.** A fixture naming a source path that does not resolve is an
authoring defect under the rule stated at the top of this log: the compiler or
consumer would correctly report a missing file. No tool was weakened and no
asserted behavior changed; the fixture remains `DISCOVERY-ONLY`.

> The pre-rename depth of `legacy_pack.dpk` was not independently captured
> before the rename, so this log does not claim what it was. What is verified
> is the state found in the finalization review, recorded in the table above.

---

## Before / after summary

| Fixture | Pre-fix evidence (host FPC) | Defect class | Fix |
|---|---|---|---|
| `delphi_classes.pas` | `Fatal: Syntax error, "BEGIN" expected but "identifier UNDER" found` | directive nested in comment | header reword |
| `delphi_classes.pas` | *(masked; probe `F1`)* `Illegal unit name: DelphiClasses` | unit name ≠ file name | file → `DelphiClasses.pas` |
| `delphi_style_app.dpr` | `Fatal: Can't find unit DelphiClasses` | cascade of the above | resolved by 1b |
| `mode_objfpc.pas` | FPC PASS; parsers rejected | directive nested in comment | header reword |
| `variant_record.pas` | `Error in type definition` | invalid type syntax | `ShortString[31]` → `string[31]` |
| `nested_routines.pas` | `Illegal unit name: NestedRoutines` | unit name ≠ file name | file → `NestedRoutines.pas` |
| `exception_flow.pas` | `Identifier not found "Exception"` | missing `uses` | add `uses SysUtils;` |
| `file_io.pas` | `Identifier not found "AssignFile"` | missing mode directive | add `{$mode objfpc}` |
| `ado_style_connection.pas` | PASS (Windows) | false header expectation | header documents platform split |
| `lazarusapp.lpr` | `Can't find unit Forms` | — | **unchanged, intended** |
| `uMainForm.pas` | `Can't find unit Forms` | — | **unchanged, intended** |
| `bde_style_query.pas` | `Can't find unit DBTables` | — | **unchanged, intended** |

## Result

| Sweep | Pre-fix | Post-fix |
|---|---|---|
| Host FPC 3.2.2 (`fpc-host-prefix.txt` → `fpc-host.txt`) | 15 PASS / 9 FAIL | **21 PASS / 3 FAIL** |
| DelphiAST (`delphiast.txt`) | baseline not preserved¹ | **24/24 PASS** |
| tree-sitter 0.24.5 (`treesitter.txt`) | baseline not preserved¹ | **24/24 PASS** |

¹ Only the host-FPC pre-fix sweep was captured to a file before the fixes were
applied; the parser sweeps were re-run after fixing and their pre-fix output was
overwritten rather than archived. The parser-side defects are still documented
above from the reproduced errors (1a and 2: both parsers rejected the two
malformed header comments; section 3: `ShortString[31]`). This row is recorded
as an evidence gap rather than as a number, so the report does not cite a
baseline that cannot be re-read from `evidence/`.

The 3 remaining host-FAIL fixtures are exactly the declared `FAIL-DEPENDENCY`
set: `lazarusapp.lpr` + `uMainForm.pas` (unit `Forms`), `bde_style_query.pas`
(unit `DBTables`). No fixture was weakened to reach these numbers.
