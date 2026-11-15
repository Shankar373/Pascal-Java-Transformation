{ P0 fixture — Lazarus-style program entry for discovery tests.
  FAIL-DEPENDENCY expected when LCL is absent: unit 'Forms' cannot be found. }
program LazarusApp;
{$mode objfpc}
uses
  Forms, uMainForm;
begin
  Application.Initialize;
  Application.Run;
end.
