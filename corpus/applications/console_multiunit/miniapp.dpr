{ P0 fixture — application: multi-unit console program (cross-unit symbol resolution).
  Build: fpc miniapp.dpr  (units resolved from the same directory) }
program MiniApp;
{$mode objfpc}
uses
  SysUtils, uMath, uReport;
begin
  writeln(ReportTotal(Square(7) + SumRange(1, 3)));
  if ParamCount > 0 then
    writeln('arg=', ParamStr(1))
end.
