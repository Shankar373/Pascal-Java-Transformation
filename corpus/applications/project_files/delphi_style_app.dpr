{ P0 fixture — application: Delphi-style program file for discovery tests.
  DISCOVERY-ONLY under FPC unless compiled with -Mdelphi and Delphi RTL available. }
program DelphiStyleApp;
{$mode delphi}
uses
  SysUtils, DelphiClasses;

var
  Calc: TCalculator;
begin
  Calc := TCalculator.Create;
  try
    Calc.Add(10.50);
    Calc.Add(0.49);
    writeln('calc total=', Calc.Total:0:2);
    try
      Calc.Add(-1);
    except
      on E: Exception do
        writeln('expected error=', E.ClassName);
    end;
  finally
    Calc.Free;
  end;
end.
